"""The deliberation room.

AutoGen orchestrates the argument; Backstop meters every call it makes. The room
recommends and never executes.
"""

from backstop_deliberation.bridge import BackstopChatCompletionClient, FreeText
from backstop_deliberation.room import (
    ARBITER,
    DEFAULT_MAX_MESSAGES,
    ROLES,
    DeliberationRecord,
    DeliberationRoom,
    Role,
)

__all__ = [
    "ARBITER",
    "DEFAULT_MAX_MESSAGES",
    "ROLES",
    "BackstopChatCompletionClient",
    "DeliberationRecord",
    "DeliberationRoom",
    "FreeText",
    "Role",
]
