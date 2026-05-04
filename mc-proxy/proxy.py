import asyncio
import logging
import time
from typing import Dict, Optional

from .events import EventType, McEvent, WebhookDispatcher
from .filter_engine import FilterEngine
from .protocol import (
    decode_string,
    decode_uuid,
    decode_varint,
    make_packet,
    read_raw_packet,
    write_varint,
)
from .server_manager import ServerManager

logger = logging.getLogger(__name__)

STATE_HANDSHAKING = 0
STATE_STATUS = 1
STATE_LOGIN = 2
STATE_CONFIGURATION = 3
STATE_PLAY = 4


class Connection:
    """Manages one proxied client ↔ backend-server session."""

    def __init__(
        self,
        cr: asyncio.StreamReader,
        cw: asyncio.StreamWriter,
        sr: asyncio.StreamReader,
        sw: asyncio.StreamWriter,
        config: dict,
        dispatcher: WebhookDispatcher,
        filter_engine: FilterEngine,
        server_mgr: ServerManager,
        active_players: Dict[str, "Connection"],
    ):
        self.cr, self.cw = cr, cw
        self.sr, self.sw = sr, sw
        self.config = config
        self.dispatcher = dispatcher
        self.filter_engine = filter_engine
        self.server_mgr = server_mgr
        self.active_players = active_players

        self.client_state = STATE_HANDSHAKING
        self.server_state = STATE_HANDSHAKING
        self.compression = -1

        self.player_name: Optional[str] = None
        self.player_uuid: Optional[str] = None
        self.client_ip: str = cw.get_extra_info("peername", ("unknown", 0))[0]

        self._pkt: dict = config.get("packet_ids", {})

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        t1 = asyncio.create_task(self._client_to_server())
        t2 = asyncio.create_task(self._server_to_client())
        done, pending = await asyncio.wait(
            [t1, t2], return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await self._cleanup()

    async def _cleanup(self) -> None:
        if self.player_name:
            evt = McEvent(
                event=EventType.PLAYER_LEAVE,
                timestamp=time.time(),
                player=self.player_name,
                uuid=self.player_uuid,
                ip=self.client_ip,
            )
            if self.player_uuid:
                self.active_players.pop(self.player_uuid, None)
            await self.dispatcher.dispatch(evt)
            await self.filter_engine.evaluate(evt)
        for w in (self.cw, self.sw):
            try:
                if not w.is_closing():
                    w.close()
                    await w.wait_closed()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Relay loops
    # ------------------------------------------------------------------

    async def _client_to_server(self) -> None:
        try:
            while True:
                raw, payload = await read_raw_packet(self.cr, self.compression)
                await self._on_client_packet(payload)
                self.sw.write(raw)
                await self.sw.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, EOFError, BrokenPipeError):
            pass

    async def _server_to_client(self) -> None:
        try:
            while True:
                raw, payload = await read_raw_packet(self.sr, self.compression)
                drop = await self._on_server_packet(payload)
                if not drop:
                    self.cw.write(raw)
                    await self.cw.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, EOFError, BrokenPipeError):
            pass

    # ------------------------------------------------------------------
    # Packet inspection: client → server
    # ------------------------------------------------------------------

    async def _on_client_packet(self, payload: bytes) -> None:
        if not payload:
            return
        try:
            packet_id, pos = decode_varint(payload)
        except Exception:
            return

        if self.client_state == STATE_HANDSHAKING:
            if packet_id == 0x00:  # Handshake
                try:
                    _, pos = decode_varint(payload, pos)   # protocol version
                    _, pos = decode_string(payload, pos)   # server address
                    pos += 2                               # server port (uint16)
                    next_state, _ = decode_varint(payload, pos)
                    if next_state == 1:
                        self.client_state = self.server_state = STATE_STATUS
                    elif next_state == 2:
                        self.client_state = self.server_state = STATE_LOGIN
                except Exception:
                    pass

        elif self.client_state == STATE_LOGIN:
            login_start_id = self._pkt.get("login_start", 0x00)
            login_ack_id = self._pkt.get("login_acknowledged", 0x03)
            if packet_id == login_start_id:
                try:
                    name, _ = decode_string(payload, pos)
                    self.player_name = name
                    logger.info("Login: %s from %s", name, self.client_ip)
                except Exception:
                    pass
            elif packet_id == login_ack_id:
                self.client_state = STATE_CONFIGURATION

        elif self.client_state == STATE_CONFIGURATION:
            ack_id = self._pkt.get("ack_finish_configuration", 0x03)
            if packet_id == ack_id:
                self.client_state = STATE_PLAY

        elif self.client_state == STATE_PLAY:
            chat_id = self._pkt.get("chat_message", 0x06)
            cmd_id = self._pkt.get("chat_command", 0x04)
            try:
                if packet_id == chat_id:
                    msg, _ = decode_string(payload, pos)
                    evt = McEvent(
                        event=EventType.PLAYER_CHAT,
                        timestamp=time.time(),
                        player=self.player_name,
                        uuid=self.player_uuid,
                        ip=self.client_ip,
                        message=msg,
                    )
                    await self.dispatcher.dispatch(evt)
                    await self.filter_engine.evaluate(evt)
                elif packet_id == cmd_id:
                    cmd, _ = decode_string(payload, pos)
                    evt = McEvent(
                        event=EventType.PLAYER_COMMAND,
                        timestamp=time.time(),
                        player=self.player_name,
                        uuid=self.player_uuid,
                        ip=self.client_ip,
                        message="/" + cmd,
                    )
                    await self.dispatcher.dispatch(evt)
                    await self.filter_engine.evaluate(evt)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Packet inspection: server → client
    # ------------------------------------------------------------------

    async def _on_server_packet(self, payload: bytes) -> bool:
        """Return True to drop the packet (replaced by a disconnect)."""
        if not payload:
            return False
        try:
            packet_id, pos = decode_varint(payload)
        except Exception:
            return False

        if self.server_state == STATE_LOGIN:
            compress_id = self._pkt.get("login_compression", 0x03)
            success_id = self._pkt.get("login_success", 0x02)
            if packet_id == compress_id:
                try:
                    threshold, _ = decode_varint(payload, pos)
                    self.compression = threshold
                    logger.debug("Compression enabled (threshold=%d)", threshold)
                except Exception:
                    pass
            elif packet_id == success_id:
                try:
                    uuid_str, pos2 = decode_uuid(payload, pos)
                    name, _ = decode_string(payload, pos2)
                    self.player_uuid = uuid_str
                    self.player_name = name
                    self.active_players[uuid_str] = self
                    evt = McEvent(
                        event=EventType.PLAYER_JOIN,
                        timestamp=time.time(),
                        player=name,
                        uuid=uuid_str,
                        ip=self.client_ip,
                    )
                    logger.info("Player joined: %s (%s)", name, uuid_str)
                    await self.dispatcher.dispatch(evt)
                    await self.filter_engine.evaluate(evt)
                except Exception as exc:
                    logger.debug("Could not parse Login Success: %s", exc)
                self.server_state = STATE_CONFIGURATION

        elif self.server_state == STATE_CONFIGURATION:
            finish_id = self._pkt.get("finish_configuration", 0x03)
            if packet_id == finish_id:
                self.server_state = STATE_PLAY

        return False

    # ------------------------------------------------------------------
    # Active disconnect (kick/ban)
    # ------------------------------------------------------------------

    async def send_disconnect(self, reason: str) -> None:
        if self.client_state == STATE_LOGIN:
            pkt_id = self._pkt.get("disconnect_login", 0x00)
        elif self.client_state == STATE_CONFIGURATION:
            pkt_id = self._pkt.get("disconnect_configuration", 0x02)
        else:
            pkt_id = self._pkt.get("disconnect_play", 0x1D)

        reason_escaped = reason.replace('"', '\\"')
        reason_json = f'{{"text":"{reason_escaped}"}}'
        reason_bytes = reason_json.encode("utf-8")
        payload = write_varint(pkt_id) + write_varint(len(reason_bytes)) + reason_bytes
        wire = make_packet(payload, self.compression)
        try:
            self.cw.write(wire)
            await self.cw.drain()
        except Exception:
            pass
        try:
            if not self.cw.is_closing():
                self.cw.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Proxy orchestrator
# ---------------------------------------------------------------------------


class MinecraftProxy:
    def __init__(self, config: dict):
        self.config = config
        self.server_mgr = ServerManager(config)
        self.dispatcher = WebhookDispatcher(config)
        self.active_players: Dict[str, Connection] = {}
        self.filter_engine = FilterEngine(
            config,
            ban_fn=self._ban_player,
            kick_fn=self._kick_player,
        )

        proxy_cfg = config.get("proxy", {})
        self.host: str = proxy_cfg.get("host", "0.0.0.0")
        self.port: int = proxy_cfg.get("port", 25565)

        backend_cfg = config.get("backend", {})
        self.backend_host: str = backend_cfg.get("host", "127.0.0.1")
        self.backend_port: int = backend_cfg.get("port", 25566)

    # ------------------------------------------------------------------
    # Ban / kick helpers (called by FilterEngine and the API)
    # ------------------------------------------------------------------

    async def _ban_player(
        self, player: Optional[str], uuid: Optional[str], reason: str
    ) -> None:
        if not player:
            return
        evt = McEvent(
            event=EventType.PLAYER_BANNED,
            timestamp=time.time(),
            player=player,
            uuid=uuid,
            reason=reason,
        )
        try:
            await self.server_mgr.ban(player, uuid, reason)
        except Exception as exc:
            logger.error("Ban command failed: %s", exc)
        conn = self._find_connection(uuid, player)
        if conn:
            await conn.send_disconnect(f"Banned: {reason}")
        await self.dispatcher.dispatch(evt)

    async def _kick_player(self, player: Optional[str], reason: str) -> None:
        if not player:
            return
        evt = McEvent(
            event=EventType.PLAYER_KICKED,
            timestamp=time.time(),
            player=player,
            reason=reason,
        )
        try:
            await self.server_mgr.kick(player, reason)
        except Exception as exc:
            logger.error("Kick command failed: %s", exc)
        conn = self._find_connection(None, player)
        if conn:
            await conn.send_disconnect(reason)
        await self.dispatcher.dispatch(evt)

    def _find_connection(
        self, uuid: Optional[str], player: Optional[str]
    ) -> Optional[Connection]:
        if uuid and uuid in self.active_players:
            return self.active_players[uuid]
        if player:
            for conn in self.active_players.values():
                if conn.player_name == player:
                    return conn
        return None

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    async def _handle_client(
        self, cr: asyncio.StreamReader, cw: asyncio.StreamWriter
    ) -> None:
        peer = cw.get_extra_info("peername", ("?", 0))
        logger.info("Incoming connection from %s:%d", *peer)

        # On-join autostart: bring up the server if it's not running
        if self.server_mgr.autostart and not self.server_mgr.is_running:
            logger.info("Server offline — starting on player join")
            await self.server_mgr.start()
            try:
                await self.server_mgr.wait_ready(timeout=120.0)
            except asyncio.TimeoutError:
                logger.warning("Server start timed out; connecting anyway")

        try:
            sr, sw = await asyncio.open_connection(
                self.backend_host, self.backend_port
            )
        except OSError as exc:
            logger.error(
                "Cannot reach backend %s:%d — %s",
                self.backend_host,
                self.backend_port,
                exc,
            )
            cw.close()
            return

        conn = Connection(
            cr, cw, sr, sw,
            self.config, self.dispatcher, self.filter_engine,
            self.server_mgr, self.active_players,
        )
        await conn.run()

    async def start(self) -> asyncio.AbstractServer:
        if self.server_mgr.autostart:
            await self.server_mgr.start()
            try:
                logger.info("Waiting for Minecraft server to be ready...")
                await self.server_mgr.wait_ready(timeout=120.0)
            except asyncio.TimeoutError:
                logger.warning("Ready-wait timed out; proxy will start anyway")

            evt = McEvent(event=EventType.SERVER_START, timestamp=time.time())
            await self.dispatcher.dispatch(evt)

        server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        logger.info(
            "Proxy listening on %s:%d → %s:%d",
            self.host, self.port, self.backend_host, self.backend_port,
        )
        return server

    async def stop(self) -> None:
        evt = McEvent(event=EventType.SERVER_STOP, timestamp=time.time())
        await self.dispatcher.dispatch(evt)
        await self.server_mgr.stop()
        await self.dispatcher.close()
