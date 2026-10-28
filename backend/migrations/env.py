"""Alembic environment. The DB URL comes from Settings (env var DATABASE_URL)."""

import importlib
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.db import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# A URL set programmatically (e.g. by tests) wins over Settings.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL.replace("%", "%%"))

MODULES = (
    "identity",
    "lists",
    "catalog",
    "pricing",
    "ingestion",
    "receipts",
    "matching",
    "trust",
    "quota",
    "spending",
    "geo",
)
for _module in MODULES:
    importlib.import_module(f"app.modules.{_module}.models")

target_metadata = Base.metadata

# Objects owned by PostGIS (and its tiger/topology schemas) are not ours; never autogenerate them.
EXCLUDED_TABLES = {"spatial_ref_sys"}


def include_name(name: str | None, type_: str, parent_names: Any) -> bool:
    if type_ == "schema":
        return name in (None, "public")
    if type_ == "table":
        return name not in EXCLUDED_TABLES
    return True


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    schema = getattr(obj, "schema", None)
    if schema not in (None, "public"):
        return False
    return not (type_ == "table" and name in EXCLUDED_TABLES)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_name=include_name,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
