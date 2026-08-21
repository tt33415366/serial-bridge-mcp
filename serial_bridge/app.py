#!/usr/bin/env python3
"""Visual dual-serial console: Bridge mode (agent+you) or CRT mode (release ports)."""
from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI
from serial_bridge.config import APP_DIR, load_config_from_args
from fastapi.staticfiles import StaticFiles
from serial_bridge.constants import HUB_PORT
from serial_bridge.hub import Hub
from serial_bridge.mcp_server import create_mcp, mount_mcp, serial_exec
from serial_bridge.operator import register_operator_routes, ws_endpoint
from serial_bridge.setup import register_setup_routes
from serial_bridge.token_store import init_token_store

STATIC = APP_DIR / "static"
OPEN_UI_ENV = "SERIAL_BRIDGE_OPEN_UI"
OPEN_UI_DISABLE_VALUES = frozenset({"0", "false", "no", "off"})
CONSOLE_UI_URL = f"http://127.0.0.1:{HUB_PORT}/"
# Agents and the console hold streams open indefinitely, so an unbounded
# graceful shutdown never ends and Ctrl-C cannot stop the Hub.
SHUTDOWN_GRACE_SECONDS = 3
_open_ui_on_startup = False

hub = Hub()
mcp = create_mcp()


def resolve_open_ui(
    *,
    environ: Mapping[str, str] | None = None,
    cli_open_ui: bool | None = None,
) -> bool:
    """Return whether to open the console UI after the Hub listens."""
    if cli_open_ui is not None:
        return cli_open_ui
    import os

    env = os.environ if environ is None else environ
    raw = env.get(OPEN_UI_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in OPEN_UI_DISABLE_VALUES


def parse_startup_args(argv: list[str] | None = None) -> tuple[list[str], bool | None]:
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--open-ui", action="store_true")
    group.add_argument("--no-open-ui", action="store_true")
    args, remaining = parser.parse_known_args(argv)
    if args.open_ui:
        return remaining, True
    if args.no_open_ui:
        return remaining, False
    return remaining, None


def open_console_ui(*, port: int = HUB_PORT, webbrowser_module=None) -> None:
    import webbrowser

    browser = webbrowser if webbrowser_module is None else webbrowser_module
    url = f"http://127.0.0.1:{port}/"
    try:
        if not browser.open(url):
            print(f"WARNING: Could not open browser at {url}")
    except OSError as exc:
        print(f"WARNING: Could not open browser at {url}: {exc}")


@asynccontextmanager
async def _lifespan(_: FastAPI):
    hub.loop = asyncio.get_running_loop()
    async with mcp.session_manager.run():
        if _open_ui_on_startup:
            open_console_ui()
        yield


app = FastAPI(title="Serial Console", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
register_setup_routes(app, STATIC)
register_operator_routes(app, STATIC)

mount_mcp(app, mcp)


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    global hub, _open_ui_on_startup
    remaining_argv, cli_open_ui = parse_startup_args(argv)
    _open_ui_on_startup = resolve_open_ui(cli_open_ui=cli_open_ui)
    hub = Hub(load_config_from_args(remaining_argv))
    init_token_store(config_path=hub.config.path)

    print(f"Starting UI at http://127.0.0.1:{HUB_PORT} (listening on 0.0.0.0)")
    bindings = " / ".join(
        f"{cfg['com']} {cfg.get('name', '?')} ({cfg.get('title', '?')}) @ {cfg['baud']}"
        for cfg in hub.ports.values()
    )
    print(f"Port Bindings: {bindings}")
    if hub.config.warning:
        print(f"WARNING: {hub.config.warning}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=HUB_PORT,
        log_level="info",
        timeout_graceful_shutdown=SHUTDOWN_GRACE_SECONDS,
    )


if __name__ == "__main__":
    main()
