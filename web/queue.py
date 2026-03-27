"""串行分析任务队列。"""
import asyncio
import logging
from datetime import datetime, timezone

from src.analyzer import LOG_DIR, run_full_analysis
from src.pub_downloader import REPOS_DIR, cleanup_plugin
from web import db as database

logger = logging.getLogger(__name__)

CONCURRENCY = 20

# 运行中的 run_id 集合，用于 API 端点判断 done=False
running_runs: set[int] = set()


# ── Analysis Queue ────────────────────────────────────────────────────────────

class AnalysisQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self._in_progress: list[dict] = []
        self._pending: list[dict] = []
        self._cancelled: set[int] = set()

    @property
    def size(self) -> int:
        return len(self._pending)

    @property
    def current(self) -> list[dict]:
        return list(self._in_progress)

    async def enqueue(self, plugin_id: int, run_id: int) -> None:
        self._pending.append({"plugin_id": plugin_id, "run_id": run_id})
        await self._queue.put((plugin_id, run_id))

    def list_pending(self) -> list[dict]:
        return list(self._pending)

    def cancel_pending(self, run_id: int) -> bool:
        if not any(p["run_id"] == run_id for p in self._pending):
            return False
        self._cancelled.add(run_id)
        self._pending = [p for p in self._pending if p["run_id"] != run_id]
        return True

    async def worker(self) -> None:
        """Permanent background loop — one of CONCURRENCY concurrent workers."""
        while True:
            plugin_id, run_id = await self._queue.get()
            self._pending = [p for p in self._pending if p["run_id"] != run_id]
            if run_id in self._cancelled:
                self._cancelled.discard(run_id)
                self._queue.task_done()
                continue
            item = {"plugin_id": plugin_id, "run_id": run_id}
            self._in_progress.append(item)
            try:
                await self._process(plugin_id, run_id)
            except Exception as exc:
                logger.exception("Unexpected error in queue worker: %s", exc)
            finally:
                self._queue.task_done()
                self._in_progress.remove(item)

    async def _process(self, plugin_id: int, run_id: int) -> None:
        plugin = await database.get_plugin(plugin_id)
        if not plugin:
            await database.update_run(run_id, "failed", error_msg="Plugin not found")
            return

        await database.update_run(run_id, "running")

        analysis_path = REPOS_DIR / plugin["name"]

        log_path = LOG_DIR / str(run_id) / "analysis.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "w", encoding="utf-8")

        async def on_log(line: str) -> None:
            log_fh.write(line + "\n")
            log_fh.flush()

        running_runs.add(run_id)
        report = None
        run_error = None
        try:
            report = await run_full_analysis(str(analysis_path), plugin["name"], on_log=on_log)
        except Exception as exc:
            run_error = str(exc)[:500]
        finally:
            log_fh.close()
            running_runs.discard(run_id)

        if run_error:
            await database.update_run(run_id, "failed",
                error_msg=run_error,
                finished_at=datetime.now(timezone.utc).isoformat())
        else:
            await database.update_run(run_id, "done",
                result=report,
                finished_at=datetime.now(timezone.utc).isoformat())

        try:
            cleanup_plugin(plugin["name"])
            await database.update_plugin_dl(plugin_id, "cleaned")
        except Exception as exc:
            logger.warning("cleanup failed: %s", exc)


analysis_queue = AnalysisQueue()
