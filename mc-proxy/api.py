import logging
import time
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from .proxy import MinecraftProxy

logger = logging.getLogger(__name__)


def _require_auth(token: str):
    def decorator(handler):
        async def wrapper(request: web.Request):
            if token:
                auth = request.headers.get("Authorization", "")
                if not auth.startswith("Bearer ") or auth[7:] != token:
                    raise web.HTTPUnauthorized(
                        text="Unauthorized",
                        headers={"WWW-Authenticate": 'Bearer realm="mc-proxy"'},
                    )
            return await handler(request)

        wrapper.__name__ = handler.__name__
        return wrapper

    return decorator


def create_api(proxy: "MinecraftProxy", config: dict) -> web.Application:
    api_cfg = config.get("api", {})
    token: str = api_cfg.get("token", "")
    auth = _require_auth(token)
    app = web.Application()

    @auth
    async def get_status(request: web.Request) -> web.Response:
        players = [
            {
                "name": c.player_name,
                "uuid": c.player_uuid,
                "ip": c.client_ip,
            }
            for c in proxy.active_players.values()
        ]
        return web.json_response(
            {
                "server_running": proxy.server_mgr.is_running,
                "server_pid": (
                    proxy.server_mgr.process.pid
                    if proxy.server_mgr.is_running
                    else None
                ),
                "players_online": len(players),
                "players": players,
                "timestamp": time.time(),
            }
        )

    @auth
    async def post_command(request: web.Request) -> web.Response:
        body = await request.json()
        cmd: str = body.get("command", "").strip()
        if not cmd:
            raise web.HTTPBadRequest(text="Missing 'command'")
        await proxy.server_mgr.send_command(cmd)
        return web.json_response({"ok": True, "command": cmd})

    @auth
    async def post_kick(request: web.Request) -> web.Response:
        body = await request.json()
        player: str = body.get("player", "").strip()
        reason: str = body.get("reason", "Kicked by admin").strip()
        if not player:
            raise web.HTTPBadRequest(text="Missing 'player'")
        await proxy._kick_player(player, reason)
        return web.json_response({"ok": True, "player": player, "reason": reason})

    @auth
    async def post_ban(request: web.Request) -> web.Response:
        body = await request.json()
        player: str = body.get("player", "").strip()
        uuid: str = body.get("uuid", "")
        reason: str = body.get("reason", "Banned by admin").strip()
        if not player:
            raise web.HTTPBadRequest(text="Missing 'player'")
        await proxy._ban_player(player, uuid or None, reason)
        return web.json_response({"ok": True, "player": player, "reason": reason})

    @auth
    async def post_server_start(request: web.Request) -> web.Response:
        await proxy.server_mgr.start()
        return web.json_response({"ok": True, "message": "Start command sent"})

    @auth
    async def post_server_stop(request: web.Request) -> web.Response:
        body: dict = {}
        try:
            body = await request.json()
        except Exception:
            pass
        timeout = float(body.get("timeout", 30))
        await proxy.server_mgr.stop(timeout=timeout)
        return web.json_response({"ok": True, "message": "Stop command sent"})

    @auth
    async def post_unban(request: web.Request) -> web.Response:
        body = await request.json()
        player: str = body.get("player", "").strip()
        if not player:
            raise web.HTTPBadRequest(text="Missing 'player'")
        await proxy.server_mgr.send_command(f"pardon {player}")
        return web.json_response({"ok": True, "player": player})

    app.router.add_get("/status", get_status)
    app.router.add_post("/command", post_command)
    app.router.add_post("/kick", post_kick)
    app.router.add_post("/ban", post_ban)
    app.router.add_post("/unban", post_unban)
    app.router.add_post("/server/start", post_server_start)
    app.router.add_post("/server/stop", post_server_stop)

    return app
