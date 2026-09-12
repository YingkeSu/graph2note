"""Desktop entry point for the Graph2Note macOS application."""

from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# graph2note.config is a pure resolution module (no gateway/network), safe to
# import before loading .env so the support dir honors GRAPH2NOTE_APP_SUPPORT.
from graph2note import config as g2n_config


APP_NAME = "Graph2Note"
HOST = "127.0.0.1"


def _bundle_resources() -> Path:
    """Return the read-only resource directory in source and frozen modes."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent / "Resources"
    return Path(__file__).resolve().parents[1]


def _support_dir() -> Path:
    path = g2n_config.support_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_env_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without adding a dotenv dependency."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def _load_runtime_config(resources: Path, support: Path) -> None:
    """Load user config before importing graph2note modules."""
    candidates = [
        support / ".env",
        resources / ".env",
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[1] / ".env",
    ]
    for candidate in candidates:
        if candidate.is_file():
            _read_env_file(candidate)
            break
    # storage resolves via graph2note.config (GRAPH2NOTE_STORAGE > <support>/storage);
    # keep the app's canonical settings location so existing configs stay visible.
    os.environ.setdefault("GRAPH2NOTE_SETTINGS_FILE", str(support / "llm-settings.json"))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status < 500:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    raise RuntimeError("Graph2Note 本地服务启动超时")


def main() -> int:
    support = _support_dir()
    log_path = support / "launcher.log"
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    resources = _bundle_resources()
    _load_runtime_config(resources, support)

    # Imports happen after configuration so gateway selection and storage paths
    # are correct in both source-tree and frozen execution.
    import uvicorn

    from graph2note.webapp import create_app

    port = _free_port()
    # A1: production enables post-ingest auto-tagging (live classify planner).
    app = create_app(auto_tag=True)
    logging.info("storage=%s settings=%s",
                 app.state.storage_dir, app.state.settings_path)
    config = uvicorn.Config(
        app,
        host=HOST,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    worker = threading.Thread(target=server.run, name="graph2note-server", daemon=True)
    worker.start()

    url = f"http://{HOST}:{port}/"
    try:
        _wait_until_ready(url)
        logging.info("started Graph2Note at %s", url)
        try:
            import webview
        except ImportError:
            # Useful when running launcher.py directly without the macOS extra.
            import webbrowser

            webbrowser.open(url)
            while worker.is_alive():
                worker.join(timeout=1.0)
        else:
            webview.create_window(
                APP_NAME,
                url,
                width=1440,
                height=960,
                min_size=(1024, 700),
                text_select=True,
            )
            webview.start(debug=False)
    except Exception:
        logging.exception("Graph2Note failed to start")
        return 1
    finally:
        server.should_exit = True
        worker.join(timeout=5.0)
        logging.info("stopped Graph2Note")
    return 0


def _handle_signal(signum, _frame) -> None:
    raise KeyboardInterrupt(f"received signal {signum}")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
