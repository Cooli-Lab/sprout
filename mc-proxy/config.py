import logging
import os
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)

DEFAULTS: Dict[str, Any] = {
    "proxy": {
        "host": "0.0.0.0",
        "port": 25565,
    },
    "backend": {
        "host": "127.0.0.1",
        "port": 25566,
    },
    "server": {
        "command": "java -jar server.jar --nogui",
        "dir": ".",
        "autostart": True,
        "ready_pattern": "Done (",
    },
    "webhooks": [],
    "event_filter": [
        "player_join",
        "player_leave",
        "player_chat",
        "player_command",
        "player_banned",
        "player_kicked",
        "server_start",
        "server_stop",
    ],
    "filters": [],
    "api": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8765,
        "token": "",
    },
    # Packet IDs for Minecraft Java Edition 1.21.4 (protocol 769).
    # Adjust if running a different server version — see wiki.vg/Protocol.
    "packet_ids": {
        "login_compression": 0x03,
        "login_success": 0x02,
        "login_start": 0x00,
        "login_acknowledged": 0x03,
        "finish_configuration": 0x03,
        "ack_finish_configuration": 0x03,
        "chat_message": 0x06,
        "chat_command": 0x04,
        "disconnect_login": 0x00,
        "disconnect_configuration": 0x02,
        "disconnect_play": 0x1D,
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        "file": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(path: str) -> Dict[str, Any]:
    config = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path, "r") as fh:
            user = yaml.safe_load(fh) or {}
        config = _deep_merge(DEFAULTS, user)
        logger.debug("Loaded config from %s", path)
    else:
        logger.warning("Config file %r not found — using defaults", path)
    return config
