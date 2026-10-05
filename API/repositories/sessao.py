"""Engine e sessao do banco para a aplicacao (B20).

Uma sessao por thread/requisicao (`scoped_session`); o server.py chama
`encerrar_sessao()` no teardown de cada requisicao. Os repositorios fazem
commit a cada escrita, como o patients_db.json gravava a cada operacao.
"""
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, scoped_session

from models import create_db_engine, make_session_factory

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

_engine: Engine | None = None
_sessoes: scoped_session | None = None


def configurar(url: str | None = None) -> Engine:
    """(Re)cria o engine. Sem `url`, usa DB_URL (backend/config.py)."""
    global _engine, _sessoes
    descartar()
    _engine = create_db_engine(url)
    _sessoes = scoped_session(make_session_factory(_engine))
    return _engine


def obter_sessao() -> Session:
    if _sessoes is None:
        configurar()
    return _sessoes()


def encerrar_sessao() -> None:
    if _sessoes is not None:
        _sessoes.remove()


def descartar() -> None:
    global _engine, _sessoes
    if _sessoes is not None:
        _sessoes.remove()
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _sessoes = None


def aplicar_migracoes(url: str | None = None) -> None:
    """`alembic upgrade head` no banco de DB_URL (ou `url`)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    # Sem isto o fileConfig do alembic.ini poe o root logger em WARNING e o
    # Flask deixa de mostrar o log das requisicoes.
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    print(f"[DB] Esquema do banco atualizado ({_engine_url(url)}).")


def _engine_url(url: str | None) -> str:
    from sqlalchemy.engine import make_url

    from backend.config import settings

    # Sem senha no log.
    return make_url(url or settings.db_url).render_as_string(hide_password=True)
