import pytest

from tsingbox.core.settings import Settings
from tsingbox.data.db import Database
from tsingbox.data.repositories.rule_files import RuleFilesRepository


@pytest.mark.asyncio
async def test_rule_files_repository_crud(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()
    repo = RuleFilesRepository(db)

    created = await repo.upsert_rule_file(
        name="Google 域名",
        tag="geosite-google",
        url="https://example.com/geosite-google.srs",
        is_builtin=False,
        auto_enabled=False,
        enabled=True,
    )

    listed = await repo.list_rule_files()
    assert any(item.tag == created.tag for item in listed)

    loaded = await repo.get_rule_file("geosite-google")
    assert loaded is not None
    assert loaded.url == "https://example.com/geosite-google.srs"
    assert loaded.format == "binary"

    loaded_again = await repo.get_rule_file("geosite-google")
    assert loaded_again is not None
    assert loaded_again.enabled is True

    deleted = await repo.delete_rule_file_by_tag("geosite-google")
    assert deleted is True
    assert await repo.get_rule_file("geosite-google") is None
