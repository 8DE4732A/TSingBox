from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    base_dir: Path = Path.home() / ".config" / "tsingbox"

    @property
    def db_path(self) -> Path:
        return self.base_dir / "tsingbox.db"

    @property
    def runtime_dir(self) -> Path:
        return self.base_dir / "runtime"

    @property
    def runtime_config_path(self) -> Path:
        return self.runtime_dir / "config.json"

    @property
    def runtime_bootstrap_config_path(self) -> Path:
        return self.runtime_dir / "bootstrap-config.json"

    @property
    def logs_dir(self) -> Path:
        return self.base_dir / "logs"

    @property
    def app_log_path(self) -> Path:
        return self.logs_dir / "app.log"

    def ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
