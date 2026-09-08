"""WebSocket publication helpers for Emby library scan tracking."""

from __future__ import annotations

import asyncio
from typing import Optional

from core.log_sanitization import format_exception_for_log
from core.safe_output import safe_print as print


class LibraryScanBroadcastMixin:
    def _broadcast_scan_completion(self, job_id: str, job_data: dict):
        """Broadcast a terminal scan event and schedule poller cleanup."""
        from emby_runtime.scan_websocket_manager import get_scan_connection_manager

        status = job_data.get("status")
        if status == "completed":
            message = {
                "type": "completed",
                "job_id": job_id,
                "summary": {
                    "total_libraries": job_data.get("total_libraries"),
                    "completed_libraries": job_data.get("completed_libraries"),
                    "started_at": job_data.get("started_at"),
                    "completed_at": job_data.get("completed_at"),
                },
            }
        elif status == "error":
            message = {
                "type": "error",
                "job_id": job_id,
                "error": job_data.get("error", "Unknown error"),
            }
        else:
            return

        try:
            from emby_runtime.library_poller import get_library_poller

            manager = get_scan_connection_manager()
            library_poller = get_library_poller()
            loop = self._get_app_event_loop()
            if loop and loop.is_running():
                manager.schedule_broadcast(loop, job_id, message)
                server_id = job_data.get("server_id")
                if server_id:
                    for library_id in job_data.get("library_ids", []):
                        asyncio.run_coroutine_threadsafe(
                            library_poller.stop_tracking_library(
                                str(server_id),
                                str(library_id),
                                expected_job_id=str(job_id),
                            ),
                            loop,
                        )
            else:
                print(f"[SCAN_BROADCAST] Warning: no event loop available for job {job_id}")
        except Exception as exc:
            self._log_flush(
                f"[SCAN_BROADCAST] Error broadcasting completion for job {job_id}:\n"
                f"{format_exception_for_log(exc)}"
            )

    def _broadcast_scan_progress(
        self,
        job_id: str,
        library_id: str,
        progress: float,
        message: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        """Broadcast a non-terminal scan progress event."""
        from emby_runtime.scan_websocket_manager import get_scan_connection_manager

        try:
            manager = get_scan_connection_manager()
            loop = self._get_app_event_loop()
            if loop and loop.is_running():
                ws_message = {
                    "type": "progress",
                    "job_id": job_id,
                    "library_id": str(library_id),
                    "progress": progress,
                    "message": message or f"Scanning library {library_id}...",
                    "source": "virtualfolders.RefreshProgress",
                }
                if metadata:
                    ws_message["metadata"] = metadata
                manager.schedule_broadcast(loop, job_id, ws_message)
                self._log_flush(
                    f"[SCAN_PROGRESS] ✓ Broadcast scheduled: job={job_id}, "
                    f"lib={library_id}, progress={progress:.1%}, msg='{message}'"
                )
            else:
                self._log_flush(
                    f"[SCAN_PROGRESS] ✗ Warning: no event loop available for job {job_id}"
                )
        except Exception as exc:
            self._log_flush(
                f"[SCAN_PROGRESS] Error broadcasting progress for job {job_id}: {exc}"
            )


__all__ = ["LibraryScanBroadcastMixin"]
