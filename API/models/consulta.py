"""Tabela `consulta` e o que pertence a ela: `mensagem`, `documento_soap`
e `consentimento`.

Apagar uma consulta apaga em cascata as mensagens, os documentos SOAP e o
consentimento (ON DELETE CASCADE no banco).
"""
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CriadoEmMixin, UuidPkMixin, enum_column, utcnow
from .enums import OrigemPep, PapelMensagem, StatusSoap, TipoConsentimento


class Consulta(UuidPkMixin, Base):
    __tablename__ = "consulta"

    paciente_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("paciente.id", ondelete="CASCADE"), nullable=False, index=True
    )
    medico_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("medico.id", ondelete="RESTRICT"), index=True
    )
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    inicio: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    origem_pep: Mapped[OrigemPep | None] = mapped_column(enum_column(OrigemPep, "origem_pep"))


class Mensagem(UuidPkMixin, Base):
    __tablename__ = "mensagem"
    __table_args__ = (Index("ix_mensagem_consulta_id_ts", "consulta_id", "ts"),)

    consulta_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("consulta.id", ondelete="CASCADE"), nullable=False
    )
    papel: Mapped[PapelMensagem] = mapped_column(
        enum_column(PapelMensagem, "papel"), nullable=False
    )
    conteudo_pseudonimizado: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class DocumentoSoap(UuidPkMixin, CriadoEmMixin, Base):
    __tablename__ = "documento_soap"

    consulta_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("consulta.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Esquema SoapV1 (US018): versao gerada pela IA e versao editada pelo medico.
    versao_ia: Mapped[dict] = mapped_column(JSON, nullable=False)
    versao_medico: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[StatusSoap] = mapped_column(
        enum_column(StatusSoap, "status_soap"), nullable=False, default=StatusSoap.GERADO
    )
    aprovado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Consentimento(Base):
    __tablename__ = "consentimento"

    # 1:1 com a consulta (US017-CA001).
    consulta_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("consulta.id", ondelete="CASCADE"), primary_key=True
    )
    tipo: Mapped[TipoConsentimento] = mapped_column(
        enum_column(TipoConsentimento, "tipo_consentimento"), nullable=False
    )
    versao_texto: Mapped[str] = mapped_column(String(32), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
