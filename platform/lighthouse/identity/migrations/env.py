"""This Alembic history is ISOLATED/STAGING ONLY; never attach to CloudBase production ledger."""
import os
from alembic import context
from sqlalchemy import engine_from_config, pool
from services.api.identity.config import load_settings
from services.api.identity.cli import isolated_guard
from domains.workforce.identity.models import Base

cfg=context.config
settings=load_settings()
isolated_guard(settings)
cfg.set_main_option("sqlalchemy.url",settings.db_a_url.replace('%','%%'))
target_metadata=Base.metadata


def run_migrations_offline():
    context.configure(url=settings.db_a_url,target_metadata=target_metadata,literal_binds=True,compare_type=True)
    with context.begin_transaction():context.run_migrations()


def run_migrations_online():
    connectable=engine_from_config(cfg.get_section(cfg.config_ini_section),prefix="sqlalchemy.",poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction():context.run_migrations()


if context.is_offline_mode():run_migrations_offline()
else:run_migrations_online()
