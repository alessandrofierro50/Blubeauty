from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.core import models  # noqa: F401  (registra i modelli)
from app.core.config import get_settings
from app.core.db import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    # Le migrazioni girano col ruolo proprietario delle tabelle.
    url = config.attributes.get("url") or get_settings().database_owner_url
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
