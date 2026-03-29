"""
智能 HTTP 代理，支持多 Provider 自动切换。

特性：
1. 检测 429/限流响应，自动切换到下一个 provider
2. 记录每个 provider 的调用量
3. 支持"用完再换"策略
"""
import http.client
import http.server
import json
import ssl
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Optional


class ProviderPool:
    """管理多个 API Provider，支持自动切换。"""
    
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = self._load_config()
        self.providers = self.config["providers"]
        self.current_index = 0
        self.call_counts = {p["name"]: 0 for p in self.providers}
        self.error_counts = {p["name"]: 0 for p in self.providers}
        self.lock = threading.Lock()
        self._last_switch_time = 0
        self._switch_cooldown = 5  # 切换后冷却 5 秒
        
    def _load_config(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        raise FileNotFoundError(f"Provider config not found: {self.config_path}")
    
    def get_current(self) -> dict:
        """获取当前活跃的 provider。"""
        with self.lock:
            return self.providers[self.current_index]
    
    def record_call(self, provider_name: str) -> None:
        """记录一次成功调用。"""
        with self.lock:
            self.call_counts[provider_name] += 1
    
    def record_error(self, provider_name: str, is_rate_limit: bool = False) -> None:
        """记录一次错误，如果是限流则切换 provider。"""
        with self.lock:
            self.error_counts[provider_name] += 1
            if is_rate_limit:
                self._switch_provider(reason=f"rate limited: {provider_name}")
    
    def _switch_provider(self, reason: str = "") -> None:
        """切换到下一个 provider。"""
        now = time.time()
        if now - self._last_switch_time < self._switch_cooldown:
            return  # 冷却期内不切换
        
        old_index = self.current_index
        old_name = self.providers[old_index]["name"]
        
        # 尝试找到下一个可用的 provider
        for i in range(1, len(self.providers)):
            next_index = (self.current_index + i) % len(self.providers)
            self.current_index = next_index
            new_name = self.providers[next_index]["name"]
            print(f"[proxy] Provider 切换: {old_name} → {new_name} ({reason})",
                  file=__import__("sys").stderr)
            self._last_switch_time = now
            return
        
        # 所有 provider 都不可用，重置到第一个
        print(f"[proxy] 所有 Provider 都已尝试，重置到第一个",
              file=__import__("sys").stderr)
        self.current_index = 0
    
    def get_stats(self) -> dict:
        """获取统计信息。"""
        with self.lock:
            return {
                "current_provider": self.providers[self.current_index]["name"],
                "call_counts": dict(self.call_counts),
                "error_counts": dict(self.error_counts),
            }


# 全局 provider pool 实例
_provider_pool: Optional[ProviderPool] = None


def get_provider_pool() -> ProviderPool:
    """获取全局 provider pool。"""
    global _provider_pool
    if _provider_pool is None:
        config_path = Path(__file__).parent.parent / "providers.json"
        _provider_pool = ProviderPool(config_path)
    return _provider_pool


class _ProxyHandler(http.server.BaseHTTPRequestHandler):
    """HTTP 代理处理器，支持多 provider 切换。"""
    
    verbose: bool = False
    provider_pool: ProviderPool = None
    
    def do_GET(self):
        self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")

    def _proxy(self, method: str) -> None:
        provider = self.provider_pool.get_current()
        base_url = provider["baseURL"]
        api_key = provider["apiKey"]
        provider_name = provider["name"]
        
        parsed = urllib.parse.urlparse(base_url)
        host = parsed.netloc
        upstream_path = parsed.path.rstrip("/") + self.path

        if self.verbose:
            print(f"[proxy] {method} {self.path} → {parsed.scheme}://{host}{upstream_path} [{provider_name}]",
                  file=__import__("sys").stderr)

        # 读请求体
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else None

        # 转发 headers，注入 Authorization
        fwd_headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in ("host", "content-length", "authorization")
        }
        fwd_headers["Authorization"] = f"Bearer {api_key}"

        if parsed.scheme == "https":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(host, context=ctx, timeout=300)
        else:
            conn = http.client.HTTPConnection(host, timeout=300)

        try:
            conn.request(method, upstream_path, body=body, headers=fwd_headers)
            resp = conn.getresponse()
            
            # 检测限流
            if resp.status == 429:
                self.provider_pool.record_error(provider_name, is_rate_limit=True)
                # 递归重试（使用新的 provider）
                conn.close()
                self._proxy(method)
                return
            
            content_type = resp.getheader("Content-Type", "")

            self.send_response(resp.status)

            # 转发 headers
            for k, v in resp.getheaders():
                if k.lower() in ("transfer-encoding", "connection", "content-length"):
                    continue
                self.send_header(k, v)

            if "text/event-stream" in content_type:
                self.end_headers()
                self._stream_sse(resp, provider_name)
            else:
                data = resp.read()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                
            # 记录成功调用
            self.provider_pool.record_call(provider_name)
            
        except Exception as exc:
            self.provider_pool.record_error(provider_name)
            try:
                self.send_error(502, str(exc))
            except Exception:
                pass
        finally:
            conn.close()

    def _stream_sse(self, resp: http.client.HTTPResponse, provider_name: str) -> None:
        """逐 SSE event 读取并转发。"""
        current: list[str] = []
        has_error = False
        while True:
            raw = resp.readline()
            if not raw:
                if current:
                    result = self._flush_event(current)
                    if result == "rate_limit":
                        has_error = True
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":
                if current:
                    result = self._flush_event(current)
                    if result == "rate_limit":
                        has_error = True
                    current = []
            else:
                current.append(line)
        
        if not has_error:
            self.provider_pool.record_call(provider_name)
        else:
            self.provider_pool.record_error(provider_name, is_rate_limit=True)

    def _flush_event(self, lines: list[str]) -> Optional[str]:
        """处理 SSE event，检测限流。"""
        patched = _patch_event(lines, verbose=self.verbose)
        
        # 检测限流错误
        for line in lines:
            if line.startswith("data: "):
                try:
                    obj = json.loads(line[6:])
                    if obj.get("type") == "error":
                        error_data = obj.get("error", {})
                        error_type = error_data.get("type", "")
                        error_code = error_data.get("code", "")
                        if error_type in ("rate_limit_error", "rate_limit_exceeded") or \
                           error_code in ("rate_limit_exceeded", "429"):
                            print(f"[proxy] 检测到限流: {error_data}",
                                  file=__import__("sys").stderr)
                            return "rate_limit"
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
        
        try:
            self.wfile.write(("\n".join(patched) + "\n\n").encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        return None

    def log_message(self, format, *args):  # noqa: A002
        pass


def _patch_event(lines: list[str], verbose: bool = False) -> list[str]:
    """若 data 行是 message_start 且缺 usage，注入 usage 字段。"""
    result = []
    for line in lines:
        if line.startswith("data: "):
            try:
                obj = json.loads(line[6:])
                if (
                    obj.get("type") == "message_start"
                    and isinstance(obj.get("message"), dict)
                    and "usage" not in obj["message"]
                ):
                    obj["message"]["usage"] = {
                        "input_tokens": 0,
                        "output_tokens": 0,
                    }
                    line = "data: " + json.dumps(
                        obj, ensure_ascii=False, separators=(",", ":")
                    )
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        result.append(line)
    return result


def start_proxy(port: int = 0, verbose: bool = False) -> http.server.HTTPServer:
    """
    启动智能代理，监听 127.0.0.1:<port>。
    返回 HTTPServer 实例。
    """
    class Handler(_ProxyHandler):
        pass

    pool = get_provider_pool()
    Handler.verbose = verbose
    Handler.provider_pool = pool

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    server.provider_pool = pool
    
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.05),
        daemon=True
    )
    thread.start()
    
    print(f"[proxy] 启动于端口 {server.server_address[1]}，当前 provider: {pool.get_current()['name']}",
          file=__import__("sys").stderr)
    return server


def stop_proxy(server: http.server.HTTPServer) -> None:
    """停止代理服务器。"""
    server.shutdown()


def get_proxy_stats(server: http.server.HTTPServer) -> dict:
    """获取代理统计信息。"""
    return server.provider_pool.get_stats()
