"""Base declarativa e tipos comuns dos modelos (B19 / ADR-02).

Os tipos escolhidos funcionam igual em SQLite (desenvolvimento) e em
PostgreSQL (Docker): `Uuid` vira UUID nativo no Postgres e CHAR(32) no
SQLite; `JSON` vira json no Postgres e TEXT no SQLite; enums sao VARCHAR com
CHECK em vez de tipo nativo, para que a mesma migracao rode nos dois bancos.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, MetaData, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Nomes deterministicos para PK/FK/indices/CHECK. Sem isto o SQLite cria
# restricoes anonimas e o Alembic nao consegue altera-las depois (o modo
# batch do SQLite recria a tabela e precisa achar cada restricao pelo nome).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enum_column(enum_cls: type[enum.Enum], name: str) -> Enum:
    """VARCHAR + CHECK com os valores do enum (nao o nome do membro)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(member.value) for member in enum_cls),
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )


class UuidPkMixin:
    # sort_order: colunas de mixin entram por ultimo; o id fica primeiro.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, sort_order=-1
    )


class CriadoEmMixin:
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
