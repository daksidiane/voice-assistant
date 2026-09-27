import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

from core.config import config
from core.personality import SputnikPersonality
from core.event_bus import event_bus

logger = logging.getLogger(__name__)


class WorkTracker:
    """Monitors continuous work session duration and advises breaks (F6.1 - F6.3)."""

    def __init__(self):
        self.session_start = datetime.now()
        self.last_break_reminder: Optional[datetime] = None
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def get_session_duration(self) -> timedelta:
        """Return elapsed duration of current continuous session."""
        return datetime.now() - self.session_start

    def reset_session(self) -> None:
        """Reset session counter (e.g. after a break)."""
        self.session_start = datetime.now()
        self.last_break_reminder = None
        logger.info("Work session timer reset.")

    def _monitor_loop(self) -> None:
        """Periodic checker for continuous work duration."""
        while not self._stop_event.is_set():
            try:
                threshold_hours = float(config.get("assistant.work_break_hours", 3.0))
                now = datetime.now()
                elapsed_hours = (now - self.session_start).total_seconds() / 3600.0

                if elapsed_hours >= threshold_hours:
                    # Only notify once every 45 minutes after threshold
                    if self.last_break_reminder is None or (now - self.last_break_reminder).total_seconds() >= 2700:
                        self.last_break_reminder = now
                        msg = SputnikPersonality.get_break_reminder()
                        logger.info(f"Triggering break recommendation: {msg}")
                        event_bus.publish("break_reminder", {
                            "hours": round(elapsed_hours, 1),
                            "text": msg
                        })

            except Exception as e:
                logger.error(f"Error in work tracker monitor loop: {e}", exc_info=True)

            self._stop_event.wait(60)

    def stop(self) -> None:
        self._stop_event.set()


# Global work tracker instance
work_tracker = WorkTracker()
