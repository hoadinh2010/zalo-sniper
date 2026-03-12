import logging
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from zalosniper.web.auth import AuthManager
from zalosniper.web.routes.api import create_api_router
from zalosniper.web.routes.pages import create_pages_router

logger = logging.getLogger(__name__)

TEMPLATES_DIR = __file__.replace("app.py", "templates")
STATIC_DIR = __file__.replace("app.py", "static")


def create_app(db, auth: AuthManager, password_hash: str, bot_state: dict) -> FastAPI:
    """
    bot_state: shared mutable dict with keys:
      "bot_running": bool
      "zalo_running": bool (set by ZaloListener)
      "config": ConfigManager instance
    """
    app = FastAPI(title="ZaloSniper Dashboard", docs_url=None, redoc_url=None)

    templates = Jinja2Templates(directory=TEMPLATES_DIR)

    # Attach shared state to app
    app.state.db = db
    app.state.auth = auth
    app.state.password_hash = password_hash
    app.state.bot_state = bot_state
    app.state.templates = templates

    app.include_router(create_api_router())
    app.include_router(create_pages_router())
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # Serve downloaded images
    import os
    images_dir = os.path.join(os.getcwd(), "data", "images")
    os.makedirs(images_dir, exist_ok=True)
    app.mount("/images", StaticFiles(directory=images_dir), name="images")

    return app


async def start_web_server(app: FastAPI, host: str = "127.0.0.1", port: int = 8080) -> None:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
