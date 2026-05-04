"""Entry point: python -m mc_proxy [-c config.yml] [-d] [--pid-file PATH]"""

import argparse
import asyncio
import logging
import os
import signal
import sys

from .config import load_config
from .proxy import MinecraftProxy


def setup_logging(config: dict) -> None:
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    fmt = log_cfg.get(
        "format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handlers = [logging.StreamHandler()]
    log_file = log_cfg.get("file", "")
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(level=level, format=fmt, handlers=handlers)


def daemonize(pid_file: str) -> None:
    """Double-fork to detach from the controlling terminal."""
    if sys.platform == "win32":
        print("Daemon mode is not supported on Windows.", file=sys.stderr)
        sys.exit(1)

    # First fork
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    os.setsid()

    # Second fork
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    # Redirect standard streams to /dev/null (use a log file for output)
    with open(os.devnull, "rb", 0) as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())
    with open(os.devnull, "ab", 0) as devnull:
        os.dup2(devnull.fileno(), sys.stdout.fileno())
        os.dup2(devnull.fileno(), sys.stderr.fileno())

    if pid_file:
        with open(pid_file, "w") as fh:
            fh.write(str(os.getpid()))


async def run(config: dict) -> None:
    proxy = MinecraftProxy(config)

    api_runner = None
    api_cfg = config.get("api", {})
    if api_cfg.get("enabled", True):
        from aiohttp import web

        from .api import create_api

        api_app = create_api(proxy, config)
        api_runner = web.AppRunner(api_app)
        await api_runner.setup()
        site = web.TCPSite(
            api_runner,
            api_cfg.get("host", "127.0.0.1"),
            api_cfg.get("port", 8765),
        )
        await site.start()
        logging.getLogger(__name__).info(
            "API listening on %s:%d",
            api_cfg.get("host", "127.0.0.1"),
            api_cfg.get("port", 8765),
        )

    mc_server = await proxy.start()

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _on_signal(sig: signal.Signals) -> None:
        logging.getLogger(__name__).info("Received %s — shutting down", sig.name)
        loop.call_soon_threadsafe(stop_event.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _on_signal, sig)

    await stop_event.wait()

    mc_server.close()
    await mc_server.wait_closed()
    await proxy.stop()

    if api_runner:
        await api_runner.cleanup()

    logging.getLogger(__name__).info("Shutdown complete")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mc-proxy",
        description="Minecraft server proxy with webhooks, filters, and REST API",
    )
    parser.add_argument(
        "-c", "--config", default="config.yml", help="Path to config.yml (default: config.yml)"
    )
    parser.add_argument(
        "-d", "--daemon", action="store_true", help="Run in background daemon mode"
    )
    parser.add_argument(
        "--pid-file", default="mc-proxy.pid", help="PID file path (daemon mode only)"
    )
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config)

    if args.daemon:
        daemonize(args.pid_file)

    asyncio.run(run(config))


if __name__ == "__main__":
    main()
