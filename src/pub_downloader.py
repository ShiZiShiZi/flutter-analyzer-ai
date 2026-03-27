"""从 pub.dev（镜像）下载插件 tar.gz 并解压到 repos/<name>/"""
import json
import os
import shutil
import ssl
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

PROJECT_DIR = Path(__file__).parent.parent
REPOS_DIR = PROJECT_DIR / "repos"

_DEFAULT_MIRROR = "https://pub.flutter-io.cn"


def _pub_base() -> str:
    return os.environ.get("PUB_HOSTED_URL", _DEFAULT_MIRROR).rstrip("/")


def _fetch_json(url: str, retries: int = 3) -> dict:
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Flutter-Plugin-Analyzer/1.0"}
            )
            with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(1.5 ** attempt)
    raise last_exc


def _fetch_bytes(url: str, retries: int = 3) -> bytes:
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Flutter-Plugin-Analyzer/1.0"}
            )
            with urllib.request.urlopen(req, timeout=120, context=_ssl_ctx) as resp:
                return resp.read()
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(1.5 ** attempt)
    raise last_exc


def download_and_extract(plugin_name: str, version: str = None) -> Path:
    base = _pub_base()
    data = _fetch_json(f"{base}/api/packages/{plugin_name}")

    if version:
        target = next(
            (v for v in data.get("versions", []) if v.get("version") == version), None
        )
        if not target:
            raise RuntimeError(f"Version {version} not found for {plugin_name}")
    else:
        target = data.get("latest", {})

    archive_url = target.get("archive_url")
    if not archive_url:
        raise RuntimeError(f"No archive_url for {plugin_name}")

    # Replace pub.dev domain in archive_url with configured mirror
    for domain in ("https://pub.dev", "https://pub.flutter-io.cn"):
        if domain in archive_url:
            archive_url = archive_url.replace(domain, base)
            break

    dest = REPOS_DIR / plugin_name
    REPOS_DIR.mkdir(exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir()

    content = _fetch_bytes(archive_url)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(content)

    try:
        with tarfile.open(tmp_path, "r:gz") as tar:
            tar.extractall(dest)
    finally:
        tmp_path.unlink(missing_ok=True)

    return dest


def cleanup_plugin(name: str) -> None:
    """删除 repos/<name>/ 目录。"""
    shutil.rmtree(REPOS_DIR / name, ignore_errors=True)
