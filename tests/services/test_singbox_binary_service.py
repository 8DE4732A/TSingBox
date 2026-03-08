from __future__ import annotations

from pathlib import Path

from tsingbox.data.models import Preferences
from tsingbox.services.singbox_binary_service import SingboxBinaryService, SingboxBinaryStatus


def make_preferences(binary_path: str | None) -> Preferences:
    return Preferences(
        id=1,
        selected_node_id=None,
        routing_mode="rule",
        dns_leak_protection=False,
        warp_enabled=False,
        singbox_binary_path=binary_path,
    )


def test_normalize_file_path_keeps_original_name(tmp_path):
    service = SingboxBinaryService()
    binary = tmp_path / "sing-box"

    assert service.normalize_input(str(binary)) == str(binary)


def test_normalize_directory_appends_singbox(tmp_path):
    service = SingboxBinaryService()

    assert service.normalize_input(str(tmp_path)) == str(tmp_path / "sing-box")


def test_resolve_binary_falls_back_to_system_path(monkeypatch):
    service = SingboxBinaryService()
    expected = "/usr/local/bin/sing-box"
    monkeypatch.setattr("tsingbox.services.singbox_binary_service.shutil.which", lambda _: expected)

    result = service.resolve_binary(make_preferences(None))

    assert result.status == SingboxBinaryStatus.PATH_FOUND
    assert result.binary_path == expected


def test_validate_configured_path_not_found(tmp_path):
    service = SingboxBinaryService()

    result = service.validate_configured_path(str(tmp_path / "missing"))

    assert result.status == SingboxBinaryStatus.CONFIGURED_NOT_FOUND


def test_validate_configured_path_not_file(tmp_path):
    service = SingboxBinaryService()
    directory = tmp_path / "bin"
    directory.mkdir()
    target = directory / "sing-box"
    target.mkdir()

    result = service.validate_configured_path(str(directory))

    assert result.status == SingboxBinaryStatus.CONFIGURED_NOT_FILE


def test_validate_configured_path_not_executable(tmp_path):
    service = SingboxBinaryService()
    binary = tmp_path / "sing-box"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o644)

    result = service.validate_configured_path(str(binary))

    assert result.status == SingboxBinaryStatus.CONFIGURED_NOT_EXECUTABLE


def test_validate_configured_path_valid(tmp_path):
    service = SingboxBinaryService()
    binary = tmp_path / "sing-box"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)

    result = service.validate_configured_path(str(binary))

    assert result.status == SingboxBinaryStatus.CONFIGURED_VALID
    assert result.binary_path == str(binary)
