import logging
import re
from dataclasses import dataclass, field
from typing import Callable, List

from .events import McEvent

logger = logging.getLogger(__name__)


@dataclass
class FilterRule:
    name: str
    event_types: List[str]
    match_field: str       # "player", "ip", or "message"
    pattern: str           # regex (case-insensitive)
    action: str            # "ban" or "kick"
    reason: str = "Filtered by proxy rule"

    def matches(self, event: McEvent) -> bool:
        if event.event not in self.event_types:
            return False
        value = getattr(event, self.match_field, None)
        if value is None:
            return False
        try:
            return bool(re.search(self.pattern, value, re.IGNORECASE))
        except re.error:
            logger.error("Invalid regex in rule %r: %r", self.name, self.pattern)
            return False


class FilterEngine:
    def __init__(self, config: dict, ban_fn: Callable, kick_fn: Callable):
        self.rules: List[FilterRule] = []
        self._ban = ban_fn
        self._kick = kick_fn
        for rule_cfg in config.get("filters", []):
            try:
                self.rules.append(FilterRule(**rule_cfg))
            except TypeError as exc:
                logger.error("Invalid filter rule %s: %s", rule_cfg, exc)

    async def evaluate(self, event: McEvent) -> None:
        for rule in self.rules:
            if rule.matches(event):
                logger.info(
                    "Rule %r triggered: action=%s player=%s event=%s",
                    rule.name,
                    rule.action,
                    event.player,
                    event.event,
                )
                if rule.action == "ban":
                    await self._ban(event.player, event.uuid, rule.reason)
                elif rule.action == "kick":
                    await self._kick(event.player, rule.reason)
                return  # first matching rule wins
