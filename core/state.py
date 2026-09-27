from enum import Enum


class AssistantState(str, Enum):
    """Lifecycle states of the SPUTNIK assistant."""
    STARTING = "starting"
    IDLE = "idle"            # Sleeping, listening only for wake word (low CPU)
    ACTIVE = "active"        # Awake, listening for user command
    PROCESSING = "processing"# Processing command / querying API
    SPEAKING = "speaking"    # Speaking answer via TTS
    PAUSED = "paused"        # Microphone paused / muted
    STOPPING = "stopping"    # Shutting down
