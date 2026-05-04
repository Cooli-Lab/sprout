import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ServerManager:
    def __init__(self, config: dict):
        cfg = config.get("server", {})
        self.command: str = cfg.get("command", "java -jar server.jar --nogui")
        self.cwd: str = cfg.get("dir", ".")
        self.autostart: bool = cfg.get("autostart", True)
        self._ready_pattern: str = cfg.get("ready_pattern", "Done (")
        self.process: Optional[asyncio.subprocess.Process] = None
        self._ready = asyncio.Event()
        self._stdin_lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def start(self) -> None:
        if self.is_running:
            logger.info("Server already running (pid=%d)", self.process.pid)
            return
        logger.info("Starting Minecraft server: %s", self.command)
        self.process = await asyncio.create_subprocess_shell(
            self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=self.cwd,
        )
        self._ready.clear()
        asyncio.create_task(self._pump_logs())
        logger.info("Server started (pid=%d)", self.process.pid)

    async def _pump_logs(self) -> None:
        assert self.process and self.process.stdout
        while True:
            line = await self.process.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            logger.info("[SERVER] %s", text)
            if self._ready_pattern in text:
                self._ready.set()
        logger.info("Server process exited (code=%s)", self.process.returncode)

    async def wait_ready(self, timeout: float = 120.0) -> None:
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    async def stop(self, timeout: float = 30.0) -> None:
        if not self.is_running:
            return
        logger.info("Sending stop command to Minecraft server...")
        try:
            await self.send_command("stop")
        except Exception:
            pass
        try:
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Server did not stop gracefully; force-killing")
            self.process.kill()

    async def send_command(self, cmd: str) -> None:
        if not self.is_running or self.process.stdin is None:
            raise RuntimeError("Server is not running")
        async with self._stdin_lock:
            self.process.stdin.write((cmd + "\n").encode())
            await self.process.stdin.drain()

    async def kick(self, player: str, reason: str = "Kicked by proxy") -> None:
        # Sanitise: Minecraft player names are alphanumeric + underscore
        safe_player = "".join(c for c in player if c.isalnum() or c == "_")
        await self.send_command(f"kick {safe_player} {reason}")

    async def ban(
        self, player: str, uuid: Optional[str], reason: str = "Banned by proxy"
    ) -> None:
        safe_player = "".join(c for c in player if c.isalnum() or c == "_")
        await self.send_command(f"ban {safe_player} {reason}")
