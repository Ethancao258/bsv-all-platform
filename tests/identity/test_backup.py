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


def test_managed_catalog_restore_uses_exact_local_peer_lane(tmp_path, monkeypatch):
    import pwd
    import services.api.identity.backup as backup
    socket_dir=tmp_path/'pg-socket';socket_dir.mkdir(mode=0o700)
    socket_dir.chmod(0o700)
    archive=tmp_path/'catalog.dump';archive.write_bytes(b'pg archive bytes')
    binary=tmp_path/'pg_restore';binary.write_text('#!/bin/sh\nexit 0\n');binary.chmod(0o700)
    monkeypatch.setattr(backup,'MANAGED_PG_RESTORE_PEER_USER','bsvint-postgres')
    monkeypatch.setattr(backup,'MANAGED_PG_RESTORE_SOCKET_DIR',socket_dir)
    monkeypatch.setattr(backup,'MANAGED_PG_RESTORE_BINARY',binary)
    monkeypatch.setattr(backup.pwd,'getpwnam',lambda _: type('Account',(),{'pw_uid':os.getuid()})())
    called={}
    def run(args,**kwargs):
        called['args']=args;called['stdin']=kwargs['stdin'];called['env']=kwargs['env'];called['cwd']=kwargs['cwd']
        return type('Result',(),{'returncode':0})()
    monkeypatch.setattr(backup.subprocess,'run',run)
    target='postgresql+psycopg://bsvint-postgres@127.0.0.1:18764/bsv_identity_isolated_catalog_restore_abc123_20261124_1'
    backup._restore_postgres_peer(archive,target,peer_user='bsvint-postgres',socket_dir=socket_dir,pg_restore_binary=binary)
    args=called['args']
    assert args[:4]==['/usr/sbin/runuser','-u','bsvint-postgres','--']
    assert f'PGHOST={socket_dir}' in args and 'PGUSER=bsvint-postgres' in args
    assert '--single-transaction' in args and args[-2:]==['--dbname', 'bsv_identity_isolated_catalog_restore_abc123_20261124_1']
    assert 'PGPASSWORD' not in called['env']
    assert called['cwd']=='/'


def test_managed_catalog_restore_rejects_database_outside_unique_isolated_scope(tmp_path,monkeypatch):
    import services.api.identity.backup as backup
    target='postgresql+psycopg://bsvint-postgres@127.0.0.1:18764/bsv_all_prod'
    with pytest.raises(RuntimeError,match='unique isolated catalog restore database'):
        backup._restore_postgres_peer(tmp_path/'dump',target,peer_user='bsvint-postgres',
                                      socket_dir=tmp_path,pg_restore_binary=tmp_path/'pg_restore')


def test_managed_catalog_restore_rejects_unmanaged_cluster_port(tmp_path):
    import services.api.identity.backup as backup
    target='postgresql+psycopg://bsvint-postgres@127.0.0.1:5432/bsv_identity_isolated_catalog_restore_abc123_20261124_1'
    with pytest.raises(RuntimeError,match='unique isolated catalog restore database'):
        backup._restore_postgres_peer(tmp_path/'dump',target,peer_user='bsvint-postgres',
                                      socket_dir=tmp_path,pg_restore_binary=tmp_path/'pg_restore')
