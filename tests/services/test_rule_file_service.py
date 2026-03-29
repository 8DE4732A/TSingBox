import pytest

from tsingbox.core.settings import Settings
from tsingbox.data.db import Database
from tsingbox.data.repositories.rule_files import RuleFilesRepository
from tsingbox.services.rule_file_service import RuleFileService


@pytest.mark.asyncio
async def test_rule_file_service_ensures_builtin_rule_set(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()
    repo = RuleFilesRepository(db)
    service = RuleFileService(repository=repo)

    rule_file = await service.ensure_rule_file("geosite-cn")

    assert rule_file.tag == "geosite-cn"
    assert rule_file.enabled is False


@pytest.mark.asyncio
async def test_rule_file_service_rejects_unknown_tag(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()
    repo = RuleFilesRepository(db)
    service = RuleFileService(repository=repo)

    with pytest.raises(ValueError, match="未知 rule_set tag"):
        await service.ensure_rule_file("unknown-tag")


@pytest.mark.asyncio
async def test_rule_file_service_lists_source_and_status(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()
    repo = RuleFilesRepository(db)
    service = RuleFileService(repository=repo)

    listed = await service.list_rule_files_with_status()
    geosite_cn = next(item for item in listed if item.rule_file.tag == "geosite-cn")
    assert geosite_cn.source_text == "内置"
    assert geosite_cn.status_text == "可引用"
