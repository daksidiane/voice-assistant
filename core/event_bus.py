import logging
from typing import Callable, Dict, List, Any
import threading

logger = logging.getLogger(__name__)


class EventBus:
    """Thread-safe event bus for inter-module messaging."""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Any], None]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_name: str, handler: Callable[[Any], None]) -> None:
        """Subscribe a callback to an event name."""
        with self._lock:
            if event_name not in self._subscribers:
                self._subscribers[event_name] = []
            if handler not in self._subscribers[event_name]:
                self._subscribers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: Callable[[Any], None]) -> None:
        """Unsubscribe a callback."""
        with self._lock:
            if event_name in self._subscribers and handler in self._subscribers[event_name]:
                self._subscribers[event_name].remove(handler)

    def publish(self, event_name: str, data: Any = None) -> None:
        """Publish an event to all subscribers."""
        handlers = []
        with self._lock:
            if event_name in self._subscribers:
                handlers = list(self._subscribers[event_name])

        for handler in handlers:
            try:
                handler(data)
            except Exception as e:
                logger.error(f"Error handling event '{event_name}' in {handler}: {e}", exc_info=True)


# Global singleton event bus
event_bus = EventBus()
