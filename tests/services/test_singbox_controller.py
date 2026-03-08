import asyncio
from pathlib import Path

import pytest

from tsingbox.services.singbox_controller import SingboxController


class DummyStream:
    def __init__(self, lines: list[bytes]):
        self._lines = lines

    async def readline(self):
        if not self._lines:
            return b""
        return self._lines.pop(0)


class DummyProcess:
    def __init__(self):
        self.returncode = None
        self.stdout = DummyStream([b"line1\n"])
        self.stderr = DummyStream([b"err1\n"])

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    async def wait(self):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


@pytest.mark.asyncio
async def test_controller_lifecycle(monkeypatch, tmp_path):
    logs: list[str] = []
    controller = SingboxController(log_callback=logs.append)

    async def fake_exec(*args, **kwargs):
        return DummyProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")

    start = await controller.start(config)
    assert start.ok
    assert controller.status() == "running"

    await asyncio.sleep(0)
    assert "line1" in logs
    assert "err1" in logs

    stop = await controller.stop()
    assert stop.ok
    assert controller.status() == "stopped"


@pytest.mark.asyncio
async def test_controller_binary_not_found(monkeypatch):
    controller = SingboxController()

    async def fake_exec(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    result = await controller.start(Path("/tmp/config.json"))
    assert not result.ok
    assert "不存在" in (result.error or "")


@pytest.mark.asyncio
async def test_controller_uses_overridden_binary(monkeypatch, tmp_path):
    called_args = ()
    controller = SingboxController(binary="/custom/bin/sing-box")

    async def fake_exec(*args, **kwargs):
        nonlocal called_args
        called_args = args
        return DummyProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")

    result = await controller.start(config)

    assert result.ok
    assert called_args[0] == "/custom/bin/sing-box"
