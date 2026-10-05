"""Ambiente do Alembic (B19).

URL do banco, em ordem de prioridade:
  1. `alembic -x db_url=...` na linha de comando;
  2. `sqlalchemy.url` definido por quem chama (os testes fazem isso);
  3. DB_URL do ambiente / API/.env, via backend.config.settings.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

from models import Base, create_db_engine

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _db_url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("db_url")
    if url:
        return url
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    from backend.config import settings

    return settings.db_url


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite nao suporta ALTER TABLE para quase nada: o modo batch recria
        # a tabela. No PostgreSQL o batch vira ALTER TABLE normal.
        render_as_batch=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=_db_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_db_engine(_db_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
