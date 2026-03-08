from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class ControlResult:
    ok: bool
    error: str | None = None


class SingboxController:
    def __init__(
        self,
        binary: str = "sing-box",
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.binary = binary
        self.log_callback = log_callback or (lambda _: None)
        self._proc: asyncio.subprocess.Process | None = None
        self._log_tasks: list[asyncio.Task] = []

    async def start(self, config_path: Path) -> ControlResult:
        if self._proc and self._proc.returncode is None:
            return ControlResult(ok=True)

        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.binary,
                "run",
                "-c",
                str(config_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return ControlResult(ok=False, error="sing-box 可执行文件不存在")
        except Exception as exc:  # noqa: BLE001
            return ControlResult(ok=False, error=str(exc))

        if self._proc.stdout:
            self._log_tasks.append(asyncio.create_task(self._stream_reader(self._proc.stdout)))
        if self._proc.stderr:
            self._log_tasks.append(asyncio.create_task(self._stream_reader(self._proc.stderr)))

        await asyncio.sleep(0)
        if self._proc.returncode not in (None, 0):
            err = f"sing-box 启动失败，退出码 {self._proc.returncode}"
            return ControlResult(ok=False, error=err)

        return ControlResult(ok=True)

    async def stop(self) -> ControlResult:
        if not self._proc or self._proc.returncode is not None:
            return ControlResult(ok=True)

        self._proc.terminate()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=5.0)
        except TimeoutError:
            self._proc.kill()
            await self._proc.wait()

        for task in self._log_tasks:
            task.cancel()
        self._log_tasks.clear()
        return ControlResult(ok=True)

    async def restart(self, config_path: Path) -> ControlResult:
        stopped = await self.stop()
        if not stopped.ok:
            return stopped
        return await self.start(config_path)

    def status(self) -> str:
        if self._proc and self._proc.returncode is None:
            return "running"
        return "stopped"

    async def _stream_reader(self, stream: asyncio.StreamReader) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            self.log_callback(line.decode("utf-8", errors="replace").rstrip())
