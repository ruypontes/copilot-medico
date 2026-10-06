"""Engine e fabrica de sessoes a partir do DB_URL (backend/config.py).

O B20 (repositorios) usa `make_session_factory`; o B19 so precisa do engine
para as migracoes e os testes.
"""
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import sessionmaker


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    # O SQLite ignora FOREIGN KEY (e o ON DELETE CASCADE) sem este PRAGMA.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_engine(url: str | None = None, **kwargs) -> Engine:
    if url is None:
        from backend.config import settings

        url = settings.db_url
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
