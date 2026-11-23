from pathlib import Path
import os
import pytest
from services.api.identity.backup import make_key,create_archive,decrypt_to_isolated
from services.api.identity.config import load_settings
from services.api.identity.api import router
from domains.workforce.identity.models import Person


def test_encrypted_snapshot_restore_isolated(monkeypatch):
    settings=load_settings()
    key=Path(settings.backup_key_file)
    key.unlink(missing_ok=True)
    make_key(key)
    path=create_archive(settings)
    assert path.name.startswith("identity-A-")
    assert path.is_file() and path.read_bytes().startswith(b'BSVIDBACKUP2')
    assert b'TRA0001' not in path.read_bytes()
    decrypt_to_isolated(path,settings,dry_run=True)
    dst=Path(settings.backup_dir)/'restore-isolated.db'
    dst.unlink(missing_ok=True)
    decrypt_to_isolated(path,settings,target=str(dst),dry_run=False)
    assert dst.is_file()
    import sqlite3
    conn=sqlite3.connect(dst)
    try:
        assert conn.execute("select count(*) from bsv_identity_people").fetchone()[0]==2
    finally:conn.close()
    dst.unlink()


def test_catalog_backup_source_has_separate_filename_and_authenticated_header(monkeypatch, capsys):
    settings=load_settings()
    key=Path(settings.backup_key_file)
    key.unlink(missing_ok=True)
    make_key(key)
    monkeypatch.setenv("BSV_BACKUP_SOURCE_LABEL", "catalog")
    path=create_archive(settings)
    assert path.name.startswith("catalog-")
    decrypt_to_isolated(path,settings,dry_run=True)
    assert '"source": "catalog"' in capsys.readouterr().out
    path.unlink()


def test_backup_source_label_rejects_unknown_alias(monkeypatch):
    import pytest
    from services.api.identity.backup import create_archive
    settings=load_settings()
    key=Path(settings.backup_key_file)
    key.unlink(missing_ok=True)
    make_key(key)
    monkeypatch.setenv("BSV_BACKUP_SOURCE_LABEL", "identity-A-but-call-it-catalog")
    with pytest.raises(RuntimeError,match="Invalid backup source label"):
        create_archive(settings)


def test_bad_backup_key_permissions_blocked():
    import tempfile
    from services.api.identity.backup import get_key
    p=Path(tempfile.mkstemp(prefix='insecure-backup-key-')[1]);p.write_text('something')
    p.chmod(0o644)
    try:
        with pytest.raises(RuntimeError,match='0600'):get_key(p)
    finally:p.unlink()
