"""封装单次完整分析：启动代理 → 跑 opencode → 解析 JSON"""
import asyncio
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

from src.proxy import start_proxy, stop_proxy

PROJECT_DIR = Path(__file__).parent.parent
LOG_DIR = PROJECT_DIR / "logs"


def _make_opencode_env(tmp_home: Path, proxy_port: int) -> dict:
    """构造 opencode 运行所需的隔离环境变量。"""
    config_path = Path.home() / ".config/opencode/opencode.json"
    tmp_cfg_dir = tmp_home / ".config" / "opencode"
    tmp_cfg_dir.mkdir(parents=True)
    run_config = json.loads(config_path.read_text())
    run_config["provider"]["bailian-coding-plan"]["options"]["baseURL"] = (
        f"http://127.0.0.1:{proxy_port}"
    )
    # 增大输出 token 上限：opencode 用 model.limit.output 作为 max_tokens 发给 API
    # 同时缩小 thinking budget，避免思考链耗尽 token 配额
    for model_cfg in run_config.get("provider", {}).get("bailian-coding-plan", {}).get("models", {}).values():
        if model_cfg.get("limit"):
            model_cfg["limit"]["output"] = 32768
        thinking = model_cfg.get("options", {}).get("thinking")
        if isinstance(thinking, dict) and "budgetTokens" in thinking:
            thinking["budgetTokens"] = 1024  # 最小值，实际不会启用 extended thinking
    (tmp_cfg_dir / "opencode.json").write_text(json.dumps(run_config, indent=4))

    tmp_opencode_data = tmp_home / ".local" / "share" / "opencode"
    tmp_opencode_data.mkdir(parents=True)
    global_bin = Path.home() / ".local" / "share" / "opencode" / "bin"
    if global_bin.exists():
        (tmp_opencode_data / "bin").symlink_to(global_bin)

    return {
        **os.environ,
        "HOME":            str(tmp_home),
        "XDG_CONFIG_HOME": str(tmp_home / ".config"),
        "XDG_DATA_HOME":   str(tmp_home / ".local" / "share"),
        "XDG_CACHE_HOME":  str(tmp_home / ".cache"),
        "XDG_STATE_HOME":  str(tmp_home / ".local" / "state"),
    }


async def _run_opencode(
    cmd: list[str],
    env: dict,
    timeout: int,
    on_log: Optional[Callable[[str], Awaitable[None]]] = None,
) -> str:
    """启动 opencode 子进程，收集 stdout，返回完整输出。"""
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(PROJECT_DIR),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=10 * 1024 * 1024,  # 10MB，防止长行 LimitOverrunError
    )

    async def read_stdout() -> None:
        assert proc.stdout
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace")
            stdout_lines.append(line)
            if on_log:
                await on_log(line.rstrip("\n"))

    async def read_stderr() -> None:
        assert proc.stderr
        async for raw in proc.stderr:
            stderr_lines.append(raw.decode("utf-8", errors="replace"))

    try:
        await asyncio.wait_for(
            asyncio.gather(read_stdout(), read_stderr(), proc.wait()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"opencode 超时（{timeout}秒）")

    if proc.returncode != 0:
        stderr_excerpt = "".join(stderr_lines)[:500]
        raise RuntimeError(f"opencode 返回码: {proc.returncode}\n{stderr_excerpt}")

    return "".join(stdout_lines)


async def run_full_analysis(
    repo_path: str,
    git_url: str,
    on_log: Optional[Callable[[str], Awaitable[None]]] = None,
) -> dict:
    """全量分析：使用 flutter-analyzer agent，结果写入临时文件。"""
    result_file = Path(tempfile.gettempdir()) / f"flutter_full_{uuid.uuid4().hex}.json"

    prompt = (
        f"分析路径 {repo_path} 下的 Flutter 插件，该目录已存在，直接读取即可，禁止执行 git clone 或任何下载操作。"
        f"完成全部八步分析后，将最终 JSON 写入文件 {result_file}，禁止在对话中直接输出 JSON。"
        f"JSON 中的 repo_url 字段填写：{git_url}。"
    )

    config_path = Path.home() / ".config/opencode/opencode.json"
    base_config = json.loads(config_path.read_text())
    real_url = base_config["provider"]["bailian-coding-plan"]["options"]["baseURL"]

    proxy = start_proxy(real_url, port=0, verbose=False)
    tmp_home = Path(tempfile.mkdtemp(prefix="oc_full_"))
    try:
        env = _make_opencode_env(tmp_home, proxy.server_address[1])
        cmd = ["opencode", "run", "--agent", "flutter-analyzer", prompt]
        await _run_opencode(cmd, env, timeout=1800, on_log=on_log)
    finally:
        stop_proxy(proxy)
        shutil.rmtree(tmp_home, ignore_errors=True)

    if not result_file.exists():
        raise ValueError("flutter-analyzer 未生成结果文件，请检查 agent 日志")

    try:
        raw = result_file.read_text(encoding="utf-8")
        result_file.unlink(missing_ok=True)
        report = json.loads(raw)
        if not isinstance(report, dict):
            raise ValueError("结果文件不是 JSON 对象")
        report.setdefault("analyzed_at", datetime.now(timezone.utc).isoformat())
        return report
    except json.JSONDecodeError as e:
        result_file.unlink(missing_ok=True)
        raise ValueError(f"结果文件 JSON 解析失败: {e}")
