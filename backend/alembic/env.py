"""
Alembic environment script. Wired directly to main.py's `Base` (all models
are already defined there - see main.py section 3 DB MODELS) and
`settings.database_url`, so migrations always reflect the exact same models
the app runs against - there is no separate models module to fall out of sync.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import Base, settings  # noqa: E402

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
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
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
