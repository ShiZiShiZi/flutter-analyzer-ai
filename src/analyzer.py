"""封装单次完整分析：使用全局代理 → 跑 opencode → 解析 JSON"""
import asyncio
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

PROJECT_DIR = Path(__file__).parent.parent
LOG_DIR = PROJECT_DIR / "logs"

# 全局代理固定端口（与 web/app.py 保持一致）
PROXY_PORT = 8765


def _make_opencode_env(tmp_home: Path, work_dir: Path) -> dict:
    """构造 opencode 运行所需的隔离环境变量。"""
    config_path = Path.home() / ".config/opencode/opencode.json"
    tmp_cfg_dir = tmp_home / ".config" / "opencode"
    tmp_cfg_dir.mkdir(parents=True)
    run_config = json.loads(config_path.read_text())
    
    # 指向全局代理（支持多 provider 自动切换）
    run_config["provider"]["bailian-coding-plan"]["options"]["baseURL"] = (
        f"http://127.0.0.1:{PROXY_PORT}"
    )
    
    # 增大输出 token 上限，缩小 thinking budget
    for model_cfg in run_config.get("provider", {}).get("bailian-coding-plan", {}).get("models", {}).values():
        if model_cfg.get("limit"):
            model_cfg["limit"]["output"] = 32768
        thinking = model_cfg.get("options", {}).get("thinking")
        if isinstance(thinking, dict) and "budgetTokens" in thinking:
            thinking["budgetTokens"] = 1024
    
    (tmp_cfg_dir / "opencode.json").write_text(json.dumps(run_config, indent=4))

    tmp_opencode_data = tmp_home / ".local" / "share" / "opencode"
    tmp_opencode_data.mkdir(parents=True)
    global_bin = Path.home() / ".local" / "share" / "opencode" / "bin"
    if global_bin.exists():
        (tmp_opencode_data / "bin").symlink_to(global_bin)

    # 只有当工作目录不是 PROJECT_DIR 时，才需要复制 .opencode 配置
    # 如果工作目录就是 PROJECT_DIR，.opencode 已经存在，无需复制
    if work_dir != PROJECT_DIR:
        opencode_dir = PROJECT_DIR / ".opencode"
        if opencode_dir.exists():
            shutil.copytree(opencode_dir, work_dir / ".opencode", dirs_exist_ok=True)

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
    work_dir: Path,
    timeout: int,
    on_log: Optional[Callable[[str], Awaitable[None]]] = None,
) -> str:
    """启动 opencode 子进程，收集 stdout，返回完整输出。"""
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    if on_log:
        await on_log(f"[opencode] 启动命令: {' '.join(cmd)}")
        await on_log(f"[opencode] 工作目录: {work_dir}")
        await on_log(f"[proxy] 使用全局代理端口: {PROXY_PORT}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(work_dir),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=10 * 1024 * 1024,
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
            line = raw.decode("utf-8", errors="replace")
            stderr_lines.append(line)
            if on_log:
                await on_log(f"[stderr] {line.rstrip()}")

    try:
        await asyncio.wait_for(
            asyncio.gather(read_stdout(), read_stderr(), proc.wait()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        if on_log:
            await on_log(f"[opencode] 超时被杀（{timeout}秒）")
        raise RuntimeError(f"opencode 超时（{timeout}秒）")

    if proc.returncode != 0:
        stderr_excerpt = "".join(stderr_lines)[:500]
        if on_log:
            await on_log(f"[opencode] 返回码: {proc.returncode}")
            await on_log(f"[opencode] stderr: {stderr_excerpt}")
        raise RuntimeError(f"opencode 返回码: {proc.returncode}\n{stderr_excerpt}")

    if on_log:
        await on_log(f"[opencode] 正常结束，stdout 行数: {len(stdout_lines)}")

    return "".join(stdout_lines)


async def run_full_analysis(
    repo_path: str,
    git_url: str,
    on_log: Optional[Callable[[str], Awaitable[None]]] = None,
) -> dict:
    """全量分析：使用 flutter-analyzer agent，结果写入临时文件。"""
    result_file = Path(tempfile.gettempdir()) / f"flutter_full_{uuid.uuid4().hex}.json"

    # 创建临时 HOME 目录（隔离 opencode 数据）
    tmp_home = Path(tempfile.mkdtemp(prefix="oc_home_"))
    
    # 创建最小化的工作目录（避免快照整个 repos 目录）
    work_dir = Path(tempfile.mkdtemp(prefix="oc_work_"))
    
    # 复制 .opencode 配置目录到工作目录
    src_opencode = PROJECT_DIR / ".opencode"
    if src_opencode.exists():
        shutil.copytree(src_opencode, work_dir / ".opencode")
    
    # 只复制当前插件目录到工作目录（避免 external_directory 权限问题）
    plugin_name = Path(repo_path).name
    repos_dir = work_dir / "repos"
    repos_dir.mkdir()
    plugin_src = PROJECT_DIR / "repos" / plugin_name
    plugin_dest = repos_dir / plugin_name
    if plugin_src.exists():
        # 复制插件目录（而不是符号链接，避免 external_directory 检测）
        shutil.copytree(plugin_src, plugin_dest)
    
    # 使用相对路径（相对于工作目录）
    repo_rel_path = f"repos/{plugin_name}"
    
    prompt = (
        f"分析路径 {repo_rel_path} 下的 Flutter 插件，该目录已存在，直接读取即可，禁止执行 git clone 或任何下载操作。"
        f"完成全部八步分析后，将最终 JSON 写入文件 {result_file}，禁止在对话中直接输出 JSON。"
        f"JSON 中的 repo_url 字段填写：{git_url}。"
    )
    
    try:
        env = _make_opencode_env(tmp_home, work_dir)
        cmd = ["opencode", "run", "--agent", "flutter-analyzer", prompt]
        await _run_opencode(cmd, env, work_dir, timeout=1800, on_log=on_log)
    finally:
        # 清理临时目录
        shutil.rmtree(tmp_home, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)

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
