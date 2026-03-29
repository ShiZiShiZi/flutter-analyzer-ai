"""FastAPI 入口：路由、lifespan。"""
import asyncio
import csv
import io
import json
import logging
import os
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from email.utils import formatdate

from src.analyzer import LOG_DIR
from src.proxy import start_proxy, stop_proxy, get_proxy_stats
from src.pub_downloader import REPOS_DIR, cleanup_plugin, download_and_extract
from web import db as database
from web.pubdev import lookup as pubdev_lookup
from web.queue import CONCURRENCY, analysis_queue, running_runs

logger = logging.getLogger(__name__)

_DIR = Path(__file__).parent
PROJECT_DIR = _DIR.parent

_download_tasks: dict[int, asyncio.Task] = {}
_repo_locks: dict[str, asyncio.Lock] = {}


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init_db()
    dl_reset, run_reset = await database.reset_stale_states()
    if dl_reset or run_reset:
        logger.warning("重置了 %d 个下载 / %d 个分析任务（服务重启）", dl_reset, run_reset)

    # 启动智能代理（支持多 provider 自动切换），使用固定端口 8765
    PROXY_PORT = 8765
    try:
        proxy = start_proxy(port=PROXY_PORT, verbose=False)
        stats = get_proxy_stats(proxy)
        logger.info("代理已启动，端口 %d，当前 provider: %s", PROXY_PORT, stats["current_provider"])
    except OSError as e:
        logger.warning("端口 %d 已被占用，代理可能已在运行: %s", PROXY_PORT, e)
        proxy = None

    worker_tasks = [
        asyncio.create_task(analysis_queue.worker()) for _ in range(CONCURRENCY)
    ]
    yield

    for t in worker_tasks:
        t.cancel()
    for t in worker_tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass
    if proxy:
        stop_proxy(proxy)
    await database.close_db()


app = FastAPI(lifespan=lifespan, title="Flutter Plugin Analyzer")
app.mount("/static", StaticFiles(directory=str(_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(_DIR / "templates"))


def _human_size(mb: Optional[float]) -> str:
    """将 MB 浮点数格式化为人类可读字符串。"""
    if mb is None:
        return "?"
    if mb < 1:
        return f"{mb * 1024:.0f} KB"
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.1f} GB"


templates.env.filters["human_size"] = _human_size


def _to_json_pretty(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


templates.env.filters["to_json_pretty"] = _to_json_pretty


def _static_v(filename: str) -> str:
    """Return /static/<filename>?v=<mtime> to bust browser cache on file changes."""
    try:
        mtime = int((_DIR / "static" / filename).stat().st_mtime)
    except OSError:
        mtime = 0
    return f"/static/{filename}?v={mtime}"


templates.env.globals["static_v"] = _static_v


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _do_download(plugin_id: int) -> None:
    plugin = await database.get_plugin(plugin_id)
    if not plugin:
        return

    started_at = datetime.now(timezone.utc).isoformat()
    await database.update_plugin_dl(plugin_id, "running", started_at=started_at)

    try:
        loop = asyncio.get_running_loop()
        name = plugin["name"]

        lock = _repo_locks.setdefault(name, asyncio.Lock())
        async with lock:
            pub_dir = REPOS_DIR / name
            if not pub_dir.exists():
                await loop.run_in_executor(None, download_and_extract, name)

        def _calc_size() -> float:
            repo_dir = REPOS_DIR / name
            if not repo_dir.exists():
                return 0.0
            import os
            total = 0
            for dirpath, _, filenames in os.walk(repo_dir):
                for fn in filenames:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, fn))
                    except OSError:
                        pass
            return total / (1024 * 1024)

        size_mb = await loop.run_in_executor(None, _calc_size)

        done_at = datetime.now(timezone.utc).isoformat()
        await database.update_plugin_dl(
            plugin_id, "done", repo_size_mb=size_mb, done_at=done_at
        )

    except Exception as exc:
        logger.error("Download failed for plugin %d: %s", plugin_id, exc)
        await database.update_plugin_dl(plugin_id, "failed", error=str(exc)[:500])


async def _do_download_then_analyze(plugin_id: int) -> None:
    """下载完成后自动入队分析；下载失败则跳过。"""
    await _do_download(plugin_id)
    plugin = await database.get_plugin(plugin_id)
    if not plugin or plugin.get("dl_status") != "done":
        return  # 下载失败，跳过分析
    run_id = await database.create_run(plugin_id)
    await analysis_queue.enqueue(plugin_id, run_id)


def _start_download(plugin_id: int, also_analyze: bool = False) -> None:
    """创建并追踪一个下载异步任务。"""
    async def _run():
        try:
            if also_analyze:
                await _do_download_then_analyze(plugin_id)
            else:
                await _do_download(plugin_id)
        except asyncio.CancelledError:
            plugin = await database.get_plugin(plugin_id)
            if plugin:
                shutil.rmtree(REPOS_DIR / plugin["name"], ignore_errors=True)
            await database.update_plugin_dl(plugin_id, "failed", error="用户已取消")
        except Exception as exc:
            logger.exception("Unexpected error in download task for plugin %d: %s", plugin_id, exc)
            try:
                await database.update_plugin_dl(plugin_id, "failed", error=str(exc)[:500])
            except Exception:
                pass
        finally:
            _download_tasks.pop(plugin_id, None)
    task = asyncio.create_task(_run())
    _download_tasks[plugin_id] = task


# ── Page routes ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    page: int = 1,
    per_page: int = 10,
    q: str = "",
    dl: str = "all",
    run: str = "all",
):
    per_page = max(10, min(per_page, 200))
    page = max(1, page)

    plugins, total = await database.list_plugins_paged(
        page=page, per_page=per_page, q=q,
        dl_status=dl, run_status=run,
    )

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "plugins": plugins,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "q": q,
        "dl": dl,
        "run": run,
        "queue_size": analysis_queue.size,
        "current_task": analysis_queue.current,
        "dl_running_count": await database.count_downloads_running(),
    })


@app.get("/import", response_class=HTMLResponse)
async def import_page(request: Request):
    return templates.TemplateResponse("import.html", {"request": request})


@app.get("/plugins/{plugin_id}", response_class=HTMLResponse)
async def plugin_detail(request: Request, plugin_id: int):
    plugin = await database.get_plugin(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    runs = await database.list_runs_for_plugin(plugin_id)
    latest_run = runs[0] if runs else None
    result = None
    if latest_run and latest_run.get("result"):
        r = latest_run["result"]
        result = json.loads(r) if isinstance(r, str) else r
    return templates.TemplateResponse("plugin.html", {
        "request": request,
        "plugin": plugin,
        "runs": runs,
        "latest_run": latest_run,
        "result": result,
    })


# ── API: pub.dev lookup + import ──────────────────────────────────────────────

@app.post("/api/plugins/lookup")
async def lookup_plugins(body: dict):
    names = body.get("names", [])
    results = await pubdev_lookup(names)
    return JSONResponse({"results": results})


@app.post("/api/plugins/import")
async def import_plugins(body: dict):
    plugins_in = body.get("plugins", [])
    imported, skipped, errors = [], [], []
    for p in plugins_in:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        try:
            if await database.get_plugin_by_name(name):
                skipped.append(name)
                continue
            pid = await database.create_plugin(name)
            imported.append({"name": name, "id": pid})
        except Exception as exc:
            errors.append({"name": name, "error": str(exc)})
    return JSONResponse({"imported": imported, "skipped": skipped, "errors": errors})


# ── API: plugin CRUD ──────────────────────────────────────────────────────────

@app.get("/api/plugins/{plugin_id}/status")
async def plugin_status(plugin_id: int):
    plugin = await database.get_plugin(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    runs = await database.list_runs_for_plugin(plugin_id)
    latest_run = runs[0] if runs else None
    return JSONResponse({
        "plugin": plugin,
        "latest_run": latest_run,
    })


@app.delete("/api/plugins/{plugin_id}")
async def delete_plugin(plugin_id: int):
    plugin = await database.get_plugin(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    repo_dir = REPOS_DIR / plugin["name"]
    if repo_dir.exists():
        shutil.rmtree(repo_dir, ignore_errors=True)
    await database.delete_plugin(plugin_id)
    return JSONResponse({"ok": True})


# ── API: analysis ─────────────────────────────────────────────────────────────

@app.post("/api/plugins/{plugin_id}/analyze")
async def analyze_plugin(plugin_id: int):
    plugin = await database.get_plugin(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    repo_dir = REPOS_DIR / plugin["name"]
    if not repo_dir.exists():
        # 仓库不存在，先下载再分析
        _start_download(plugin_id, also_analyze=True)
        return JSONResponse({"ok": True, "queued": "download_then_analyze"})
    run_id = await database.create_run(plugin_id)
    await analysis_queue.enqueue(plugin_id, run_id)
    return JSONResponse({"ok": True, "run_id": run_id})


@app.post("/api/plugins/analyze-batch")
async def analyze_batch(body: dict):
    force = body.get("force", False)
    run_ids = []
    for pid in body.get("plugin_ids", []):
        plugin = await database.get_plugin(pid)
        if not plugin:
            continue
        if not force:
            runs = await database.list_runs_for_plugin(pid)
            if runs and runs[0]["status"] == "done":
                continue
        repo_dir = REPOS_DIR / plugin["name"]
        if not repo_dir.exists():
            _start_download(pid, also_analyze=True)
        else:
            run_id = await database.create_run(pid)
            await analysis_queue.enqueue(pid, run_id)
            run_ids.append(run_id)
    return JSONResponse({"ok": True, "run_ids": run_ids})


@app.post("/api/runs/{run_id}/rerun")
async def rerun(run_id: int):
    run = await database.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    plugin = await database.get_plugin(run["plugin_id"])
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    # 如果插件已清理，重置下载状态
    if plugin.get("dl_status") == "cleaned":
        await database.update_plugin_dl(run["plugin_id"], "pending")

    repo_dir = REPOS_DIR / plugin["name"]
    if not repo_dir.exists():
        _start_download(run["plugin_id"], also_analyze=True)
        return JSONResponse({"ok": True, "queued": "download_then_analyze"})
    new_run_id = await database.create_run(run["plugin_id"])
    await analysis_queue.enqueue(run["plugin_id"], new_run_id)
    return JSONResponse({"ok": True, "run_id": new_run_id})


@app.get("/api/plugins/{plugin_id}/runs")
async def get_runs(plugin_id: int):
    runs = await database.list_runs_for_plugin(plugin_id)
    return JSONResponse({"runs": runs})


@app.get("/api/runs/{run_id}")
async def get_run(run_id: int):
    run = await database.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return JSONResponse({"run": run})


@app.get("/api/runs/{run_id}/logs")
async def get_run_logs(run_id: int, since: int = 0):
    is_running = run_id in running_runs
    log_file = LOG_DIR / str(run_id) / "analysis.log"

    if not log_file.exists():
        response = JSONResponse({"lines": [], "total": 0, "done": True})
        return response

    mtime = log_file.stat().st_mtime
    last_modified = formatdate(mtime, usegmt=True)

    content = log_file.read_text(encoding="utf-8", errors="replace")
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]

    response = JSONResponse({"lines": lines[since:], "total": len(lines), "done": not is_running})
    response.headers['Last-Modified'] = last_modified
    return response

@app.get("/api/events")
async def sse_removed():
    """SSE 已移除，返回 410 Gone 阻止浏览器缓存的旧脚本持续重连。"""
    return Response(status_code=410)


@app.get("/api/system/status")
async def system_status():
    return JSONResponse({
        "queue_size": analysis_queue.size,
        "current_task": analysis_queue.current,
    })


@app.get("/api/providers/stats")
async def providers_stats():
    """获取多 Provider 切换统计信息。"""
    from src.proxy import get_provider_pool
    try:
        pool = get_provider_pool()
        return JSONResponse(pool.get_stats())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/tasks")
async def list_tasks():
    downloads = []
    for pid, task in list(_download_tasks.items()):
        if task.done():
            continue
        plugin = await database.get_plugin(pid)
        downloads.append({
            "plugin_id": pid,
            "name": plugin["name"] if plugin else f"Plugin #{pid}",
        })
    return JSONResponse({
        "downloads": downloads,
        "analysis_current": analysis_queue.current,
        "analysis_pending": analysis_queue.list_pending(),
    })


@app.delete("/api/tasks/download/{plugin_id}")
async def cancel_download_task(plugin_id: int):
    task = _download_tasks.pop(plugin_id, None)
    if task and not task.done():
        task.cancel()
    await database.update_plugin_dl(plugin_id, "failed", error="用户已取消")
    return JSONResponse({"ok": True})


@app.delete("/api/tasks/analysis/{run_id}")
async def cancel_analysis_task(run_id: int):
    ok = analysis_queue.cancel_pending(run_id)
    if ok:
        now = datetime.now(timezone.utc).isoformat()
        await database.update_run(run_id, "failed",
            error_msg="用户已取消", finished_at=now, duration_ms=0)
    return JSONResponse({"ok": ok})


@app.get("/api/system/plugin-counts")
async def plugin_counts():
    return JSONResponse({
        "dl": await database.get_dl_status_counts(),
        "run": await database.get_run_status_counts(),
    })


# ── Export ────────────────────────────────────────────────────────────────────

CATEGORY_ZH = {
    "payment": "支付", "map_location": "地图定位",
    "push_notification": "推送通知", "im_chat": "即时通讯",
    "audio_video_call": "音视频通话", "storage": "存储",
    "file_media": "文件媒体", "networking": "网络",
    "auth_security": "认证安全", "analytics": "数据分析",
    "ads": "广告", "social_share": "社交分享",
    "ui_component": "UI组件", "device_sensor": "设备传感器",
    "bluetooth_hardware": "蓝牙硬件", "ar_xr": "AR/XR",
    "ai_ml": "AI/ML", "platform_utility": "平台工具",
}


@app.get("/export")
async def export_csv():
    plugins = await database.list_plugins()

    HDR1 = ["基本信息", "", "", "",
             "云服务", "", "", "",
             "付费", "", "", "", "",
             "许可证", "", "",
             "移动平台", "", "",
             "功能特性", "", "", "", "", "", "", "", "",
             "依赖分析", "", "", "", "", "", "", "", "", "", "", "", "", ""]
    HDR2 = ["名称", "pub.dev", "下载状态", "分析状态",
             "拓扑", "标签", "服务列表", "证据",
             "涉及付费", "插件付费", "云服务付费", "付费类型", "证据",
             "许可证类型", "许可分类", "合规风险",
             "平台标签", "置信度", "证据",
             "分类1", "标签1", "分类2", "标签2", "分类3", "标签3",
             "功能列表", "摘要", "证据",
             "依赖总数", "Native依赖数", "阻断数", "关注数", "阻断项", "关注项", 
             "有NDK", "有FFI", "NDK系统库", "FFI系统调用",
             "Native系统API", "Native系统库", "Native系统框架", "Native第三方二进制", "Native源码",
             "Native Android层", "Native iOS层", "Native跨平台"]

    DL_ZH  = {"pending": "待下载", "running": "下载中", "done": "已下载", "failed": "下载失败", "cleaned": "已清理"}
    RUN_ZH = {"pending": "待分析", "running": "分析中", "done": "已完成", "failed": "分析失败"}

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HDR1)
    w.writerow(HDR2)

    def join(v):
        if not isinstance(v, list):
            return v or ""
        return " | ".join([str(x) for x in v if x])

    def yn(v):
        return "是" if v else ("否" if v is not None else "")

    def cats(v):
        if not isinstance(v, list):
            return ""
        result = []
        for c in v:
            if c:
                translated = CATEGORY_ZH.get(c, c)
                if translated:
                    result.append(translated)
        return " | ".join(result)

    for p in plugins:
        if p.get("run_status") != "done":
            continue
        runs = await database.list_runs_for_plugin(p["id"])
        if not runs or not runs[0].get("result"):
            continue
        result_json = runs[0]["result"]
        if isinstance(result_json, str):
            result_json = json.loads(result_json)

        cs  = result_json.get("cloud_services", {})
        pay = result_json.get("payment", {})
        lic = result_json.get("license", {})
        mp  = result_json.get("mobile_platform", {})
        ft  = result_json.get("features", {})
        da  = result_json.get("dependency_analysis", {})
        da_summary = da.get("summary", {})
        da_by_risk = da_summary.get("by_risk", {})
        da_native_by_type = da_summary.get("native_by_type", {})
        da_native_by_layer = da_summary.get("native_by_layer", {})

        w.writerow([
            p["name"],
            f"https://pub.dev/packages/{p['name']}",
            DL_ZH.get(p.get("dl_status", ""), p.get("dl_status", "")),
            RUN_ZH.get(p.get("run_status", ""), p.get("run_status", "") or "未分析"),
            # cloud_services
            cs.get("topology", ""), cs.get("label", ""),
            join(cs.get("services", [])), join(cs.get("evidence", [])),
            # payment
            yn(pay.get("involves_payment")), yn(pay.get("plugin_paid")), yn(pay.get("cloud_paid")),
            join(pay.get("payment_type", [])), join(pay.get("evidence", [])),
            # license
            lic.get("declared_license") or lic.get("type", ""),
            lic.get("label") or yn(lic.get("commercial_friendly")),
            join(lic.get("risks") or lic.get("restrictions", [])),
            # mobile_platform
            mp.get("label", ""), mp.get("confidence", ""), join(mp.get("evidence", [])),
            # features
            cats(ft.get("taxonomy1", {}).get("categories", [])),
            join(ft.get("taxonomy1", {}).get("tags", [])),
            join(ft.get("taxonomy2", {}).get("categories", [])),
            join(ft.get("taxonomy2", {}).get("tags", [])),
            join(ft.get("taxonomy3", {}).get("categories", [])),
            join(ft.get("taxonomy3", {}).get("tags", [])),
            join(ft.get("feature_list", [])), ft.get("summary", ""), join(ft.get("evidence", [])),
            # dependency_analysis
            da_summary.get("total_dependencies", 0),
            da_summary.get("native_dependency_count", 0),
            da_by_risk.get("blocker", 0),
            da_by_risk.get("concern", 0),
            join(da_summary.get("blockers", [])),
            join(da_summary.get("concerns", [])),
            yn(da_summary.get("has_ndk")),
            yn(da_summary.get("has_ffi")),
            join(da_summary.get("ndk_system_libs", [])),
            join(da_summary.get("ffi_system_calls", [])),
            # native_by_type
            da_native_by_type.get("system_api", 0),
            da_native_by_type.get("system_library", 0),
            da_native_by_type.get("system_framework", 0),
            da_native_by_type.get("third_party_binary", 0),
            da_native_by_type.get("source_in_repo", 0),
            # native_by_layer
            da_native_by_layer.get("android", 0),
            da_native_by_layer.get("ios", 0),
            da_native_by_layer.get("cross_platform", 0),
        ])

    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="plugins_export.csv"'},
    )


@app.get("/export/json")
async def export_json():
    plugins = await database.list_plugins()
    result = []
    for p in plugins:
        if p.get("run_status") != "done":
            continue
        runs = await database.list_runs_for_plugin(p["id"])
        if not runs or not runs[0].get("result"):
            continue
        result_json = runs[0]["result"]
        if isinstance(result_json, str):
            result_json = json.loads(result_json)
        result.append({
            "name": p["name"],
            "pub_url": f"https://pub.dev/packages/{p['name']}",
            "dl_status": p.get("dl_status", ""),
            "run_status": p.get("run_status", ""),
            **result_json,
        })
    return Response(
        content=json.dumps(result, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="plugins_export.json"'},
    )
