from __future__ import annotations

from pathlib import Path

from tsingbox.app import TSingBoxApp
from tsingbox.core.settings import Settings


async def create_initialized_app(tmp_path: Path) -> TSingBoxApp:
    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.database.settings = app.settings
    app.settings.ensure_dirs()
    await app.database.initialize()
    return app
