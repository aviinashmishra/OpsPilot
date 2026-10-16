"""Alembic environment. Uses DATABASE_URL (env var or .env, via app settings); renders portable custom types."""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.db import models  # noqa: F401 - populate metadata
from app.db.base import Base
from app.db.types import GUID, JSONType, VectorType

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Same source as the app (env var first, then ../.env and .env), normalized to the psycopg 3 driver.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):  # type: ignore[no-untyped-def]
    """Render our TypeDecorators with an import so generated migrations stay portable."""
    if type_ == "type":
        if isinstance(obj, GUID):
            autogen_context.imports.add("from app.db.types import GUID")
            return "GUID()"
        if isinstance(obj, JSONType):
            autogen_context.imports.add("from app.db.types import JSONType")
            return "JSONType()"
        if isinstance(obj, VectorType):
            autogen_context.imports.add("from app.db.types import VectorType")
            return f"VectorType({obj.dimensions})"
    return False


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}, render_item=render_item, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_item=render_item, render_as_batch=connection.dialect.name == "sqlite", compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
