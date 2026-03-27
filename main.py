#!/usr/bin/env python3
"""
Flutter Plugin Analyzer
用法：python main.py <plugin_name> [--output <file>] [--keep] [--verbose]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.pub_downloader import cleanup_plugin, download_and_extract
from src.proxy import start_proxy, stop_proxy

PROJECT_DIR = Path(__file__).parent
OUTPUT_DIR = PROJECT_DIR / "output"


def run_opencode(repo_path: Path, repo_url: str, verbose: bool, extra_env: dict) -> str:
    prompt = (
        f"分析路径 {repo_path} 下的 Flutter 插件，该目录已存在，直接读取即可，禁止执行 git clone 或任何下载操作。"
        f"请依次使用 cloud-service-check、payment-check、license-check、features-check 四个 skill 完成分析，"
        f"最终只输出一个 JSON 对象，字段包含 repo_url、analyzed_at、cloud_services、payment、license、features。"
        f"输出 JSON 中的 repo_url 字段填写：{repo_url}。"
    )
    cmd = [
        "opencode", "run",
        "--agent", "flutter-analyzer",
        prompt,
    ]
    env = {**os.environ, **extra_env}
    if verbose:
        print(f"[opencode] 执行命令: {' '.join(cmd)}", file=sys.stderr)

    if verbose:
        # 实时流式打印输出，方便观察进度
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_DIR),
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            env=env,
        )
        stdout_lines = []
        for line in proc.stdout:
            print(line, end="", file=sys.stderr)
            stdout_lines.append(line)
        proc.wait()
        stdout = "".join(stdout_lines)
        returncode = proc.returncode
    else:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=900,
            env=env,
        )
        stdout = result.stdout
        returncode = result.returncode

    if verbose:
        print(f"[opencode] 返回码: {returncode}", file=sys.stderr)
    return stdout


_REQUIRED_KEYS = {"repo_url", "cloud_services", "payment", "license", "features"}


def extract_json(text: str) -> dict:
    """从 opencode 输出中提取包含分析结果的 JSON 对象（必须含全部顶层字段）"""
    # 去掉可能的 markdown 代码块
    text = re.sub(r"```(?:json)?\s*", "", text)
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text, m.start())
            if isinstance(obj, dict) and _REQUIRED_KEYS.issubset(obj):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError(f"输出中未找到包含所有必要字段 {_REQUIRED_KEYS} 的 JSON 对象")


def main():
    parser = argparse.ArgumentParser(description="分析 Flutter 插件")
    parser.add_argument("url", help="pub.dev package 名称（如 alipay_kit）")
    parser.add_argument("--output", "-o", help="JSON 输出路径（默认 output/<plugin_name>.json）")
    parser.add_argument("--keep", action="store_true", help="分析完成后保留克隆的临时目录")
    parser.add_argument("--verbose", "-v", action="store_true", help="打印调试信息")
    args = parser.parse_args()

    # 1. Download from pub.dev
    plugin_name = args.url  # treat positional arg as plugin name
    print(f"正在从 pub.dev 下载 {plugin_name} ...")
    try:
        repo_path = download_and_extract(plugin_name)
    except RuntimeError as e:
        print(f"下载失败: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"下载完成: {repo_path}")

    try:
        # 2. 启动透明代理（修复 Bailian API message_start 缺 usage 字段的问题）
        config_path = Path.home() / ".config/opencode/opencode.json"
        config = json.loads(config_path.read_text())
        real_url = config["provider"]["bailian-coding-plan"]["options"]["baseURL"]
        proxy = None
        tmp_home = None
        try:
            proxy = start_proxy(real_url, port=0, verbose=args.verbose)
            actual_port = proxy.server_address[1]

            # 独立临时 HOME，写入代理地址，不修改全局配置
            tmp_home = Path(tempfile.mkdtemp(prefix="opencode_run_"))
            tmp_cfg_dir = tmp_home / ".config" / "opencode"
            tmp_cfg_dir.mkdir(parents=True)
            run_config = json.loads(config_path.read_text())
            run_config["provider"]["bailian-coding-plan"]["options"]["baseURL"] = (
                f"http://127.0.0.1:{actual_port}"
            )
            (tmp_cfg_dir / "opencode.json").write_text(json.dumps(run_config, indent=4))

            # 共享全局 bin/（888MB language servers），避免 CLI 单次运行也触发重复下载
            tmp_opencode_data = tmp_home / ".local" / "share" / "opencode"
            tmp_opencode_data.mkdir(parents=True)
            global_bin = Path.home() / ".local" / "share" / "opencode" / "bin"
            if global_bin.exists():
                (tmp_opencode_data / "bin").symlink_to(global_bin)

            # 3. 调用 opencode 分析
            print("正在分析（可能需要数分钟）...")
            raw_output = run_opencode(
                repo_path, plugin_name, args.verbose, {
                    "HOME": str(tmp_home),
                    "XDG_CONFIG_HOME": str(tmp_home / ".config"),
                    "XDG_DATA_HOME":   str(tmp_home / ".local" / "share"),
                    "XDG_CACHE_HOME":  str(tmp_home / ".cache"),
                    "XDG_STATE_HOME":  str(tmp_home / ".local" / "state"),
                }
            )
        finally:
            if proxy is not None:
                stop_proxy(proxy)
            if tmp_home is not None:
                shutil.rmtree(tmp_home, ignore_errors=True)

        if args.verbose:
            print(f"[raw output]\n{raw_output}", file=sys.stderr)

        # 3. 提取 JSON
        try:
            report = extract_json(raw_output)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"JSON 解析失败: {e}", file=sys.stderr)
            print("原始输出已写入 output/raw_output.txt", file=sys.stderr)
            OUTPUT_DIR.mkdir(exist_ok=True)
            (OUTPUT_DIR / "raw_output.txt").write_text(raw_output, encoding="utf-8")
            sys.exit(1)

        # 补充 analyzed_at（如果 agent 没输出）
        report.setdefault("analyzed_at", datetime.now(timezone.utc).isoformat())

        # 4. 写出报告
        OUTPUT_DIR.mkdir(exist_ok=True)
        if args.output:
            out_path = Path(args.output)
        else:
            out_path = OUTPUT_DIR / f"{plugin_name}.json"

        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"分析完成，报告已写入: {out_path}")
        print(json.dumps(report, ensure_ascii=False, indent=2))

    finally:
        if not args.keep:
            cleanup_plugin(plugin_name)
            if args.verbose:
                print(f"[cleanup] 已删除临时目录 {repo_path}", file=sys.stderr)
        else:
            print(f"临时目录保留在: {repo_path}")


if __name__ == "__main__":
    main()
