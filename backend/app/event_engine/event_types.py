from enum import Enum

class EventType(str, Enum):
    FENCE_JUMP = "FENCE_JUMP"
    RESTRICTED_ENTRY = "RESTRICTED_ENTRY"
    LOITERING = "LOITERING"
