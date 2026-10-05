"""Conversoes comuns entre o banco e o formato JSON da API."""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session


def parse_uuid(valor) -> uuid.UUID | None:
    """IDs chegam da API como texto; qualquer coisa que nao seja UUID e
    tratada como "nao encontrado" (ex.: o legado `paciente_abc`)."""
    if isinstance(valor, uuid.UUID):
        return valor
    if not isinstance(valor, str) or not valor.strip():
        return None
    try:
        return uuid.UUID(valor.strip())
    except ValueError:
        return None


def id_texto(valor: uuid.UUID | None) -> str | None:
    return str(valor) if valor is not None else None


def iso(valor: datetime | None) -> str | None:
    # Sempre com fuso (UTC): o Postgres devolve aware e o SQLite naive; sem
    # isto o mesmo registro mudaria de formato conforme o banco. Datas
    # enviadas sem fuso pelo cliente sao tratadas como UTC.
    return como_utc(valor).isoformat() if valor is not None else None


def como_utc(valor: datetime) -> datetime:
    """O SQLite devolve datetimes sem fuso; o Postgres, com fuso. Normaliza
    para UTC aware antes de comparar."""
    if valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(timezone.utc)


def parse_data(valor) -> datetime | None:
    """Datas enviadas pelo cliente (ISO 8601). Invalidas viram None."""
    if isinstance(valor, datetime):
        return valor
    if not isinstance(valor, str) or not valor.strip():
        return None
    try:
        return datetime.fromisoformat(valor.strip())
    except ValueError:
        return None


class Repositorio:
    def __init__(self, sessao: Session):
        self.sessao = sessao
