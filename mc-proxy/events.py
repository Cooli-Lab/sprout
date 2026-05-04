import logging
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    PLAYER_JOIN = "player_join"
    PLAYER_LEAVE = "player_leave"
    PLAYER_CHAT = "player_chat"
    PLAYER_COMMAND = "player_command"
    PLAYER_BANNED = "player_banned"
    PLAYER_KICKED = "player_kicked"
    SERVER_START = "server_start"
    SERVER_STOP = "server_stop"


@dataclass
class McEvent:
    event: str
    timestamp: float
    player: Optional[str] = None
    uuid: Optional[str] = None
    ip: Optional[str] = None
    message: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class WebhookDispatcher:
    def __init__(self, config: dict):
        self._webhooks: List[dict] = []
        for w in config.get("webhooks", []):
            if isinstance(w, str):
                self._webhooks.append({"url": w})
            elif isinstance(w, dict):
                self._webhooks.append(w)

        self._filter = set(
            config.get("event_filter", [e.value for e in EventType])
        )
        self._session: Optional[aiohttp.ClientSession] = None

    def _session_or_new(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def dispatch(self, event: McEvent) -> None:
        if event.event not in self._filter:
            return
        for wh in self._webhooks:
            url = wh.get("url", "")
            if not url:
                continue
            is_discord = "discord.com" in url or "discordapp.com" in url
            if is_discord:
                d = event.to_dict()
                color = (
                    0x57F287
                    if "join" in event.event
                    else 0xED4245
                    if "leave" in event.event or "ban" in event.event
                    else 0xFEE75C
                )
                fields = [
                    {"name": k, "value": str(v), "inline": True}
                    for k, v in d.items()
                    if k != "event"
                ]
                payload = {
                    "embeds": [
                        {
                            "title": event.event.replace("_", " ").title(),
                            "fields": fields,
                            "color": color,
                            "timestamp": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ",
                                time.gmtime(event.timestamp),
                            ),
                        }
                    ]
                }
            else:
                payload = event.to_dict()
            try:
                async with self._session_or_new().post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status >= 400:
                        logger.warning("Webhook %s → HTTP %d", url, resp.status)
            except Exception as exc:
                logger.error("Webhook error for %s: %s", url, exc)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
