"""Run the app: `python -m voiceover_studio` (API under /api, UI at /)."""

from __future__ import annotations

import logging
import os

import gradio as gr
import uvicorn

from voiceover_studio.api import create_app
from voiceover_studio.core.config import load_config
from voiceover_studio.services import Services
from voiceover_studio.settings import Settings
from voiceover_studio.ui import build_ui


def build():
    services = Services(Settings.from_env(), load_config())
    app = create_app(services)
    return gr.mount_gradio_app(app, build_ui(services), path="/")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Inside the container we listen on all interfaces; the host only publishes the port on 127.0.0.1 and the
    # security group has no inbound rules, so the app is reachable only through the SSM tunnel.
    host = os.environ.get("APP_HOST", "127.0.0.1")
    uvicorn.run(build(), host=host, port=int(os.environ.get("APP_PORT", "7860")))


if __name__ == "__main__":
    main()
