"""
Progress tracking for Latest Publications system.
Provides thread-safe progress updates during background refresh operations.
Uses database persistence instead of volatile in-memory cache.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional


class ProgressTracker:
    """
    Thread-safe progress tracker with database persistence.
    Replaces the volatile _LATEST_CACHE["progress"] implementation.
    """

    def __init__(self, db_storage):
        """
        Initialize progress tracker.

        Args:
            db_storage: DatabaseStorage instance for persistence
        """
        self.db = db_storage

    def update(
        self,
        state: Optional[str] = None,
        total: Optional[int] = None,
        completed: Optional[int] = None,
        message: Optional[str] = None
    ) -> None:
        """
        Update progress tracking for background refresh operations.

        Args:
            state: Progress state ("collecting", "enriching", "done", "error", "idle")
            total: Total number of items to process
            completed: Number of items completed
            message: Status message
        """
        # Load current progress from DB
        current = self.db.load_latest_progress()

        # Update fields
        if state is not None:
            current["state"] = state
            if state in ("collecting", "enriching"):
                current["started_at"] = datetime.now(timezone.utc).isoformat()
        if total is not None:
            current["total"] = total
        if completed is not None:
            current["completed"] = completed
        if message is not None:
            current["message"] = message

        # Save back to DB (updated_at is auto-updated by ORM)
        self.db.save_latest_progress(current)

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Get current progress snapshot from database.

        Returns:
            Dict containing:
                - state: Current state string
                - total: Total items count
                - completed: Completed items count
                - message: Status message
                - started_at: ISO timestamp when operation started
                - updated_at: ISO timestamp of last update
        """
        return self.db.load_latest_progress()


# Singleton instance (initialized by manager)
_tracker: Optional[ProgressTracker] = None


def get_tracker(db_storage) -> ProgressTracker:
    """
    Get or create the global ProgressTracker instance.

    Args:
        db_storage: DatabaseStorage instance

    Returns:
        ProgressTracker singleton
    """
    global _tracker
    if _tracker is None:
        _tracker = ProgressTracker(db_storage)
    return _tracker
