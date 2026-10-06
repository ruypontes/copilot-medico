"""Tabela `medico`: todo usuario do sistema (medicos e administradores).

Decisao do B19: em vez de uma tabela `usuario` separada, `medico` foi
ampliada com os campos que o Grupo 2 criou no users_db.json (perfis,
aprovacao, especialidade, ativo). O administrador e uma linha com
perfis=["administrador"], sem CRM e sem status de aprovacao.
"""
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CriadoEmMixin, UuidPkMixin, enum_column
from .enums import StatusAprovacao


class Medico(UuidPkMixin, CriadoEmMixin, Base):
    __tablename__ = "medico"

    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    crm: Mapped[str | None] = mapped_column(String(32))
    especialidade: Mapped[str | None] = mapped_column(String(120))
    # Lista de perfis, ex.: ["medico"], ["administrador"], ["administrador", "medico"].
    perfis: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Fluxo de aprovacao do cadastro de medico (nulo para quem nao e medico).
    status_aprovacao: Mapped[StatusAprovacao | None] = mapped_column(
        enum_column(StatusAprovacao, "status_aprovacao")
    )
    aprovado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aprovado_por_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("medico.id", ondelete="SET NULL")
    )
    rejeitado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejeitado_por_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("medico.id", ondelete="SET NULL")
    )
    motivo_rejeicao: Mapped[str | None] = mapped_column(Text)
