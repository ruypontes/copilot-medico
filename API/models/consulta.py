"""Tabela `consulta` e o que pertence a ela: `mensagem`, `documento_soap`,
`consentimento`, `mapa_anonimizacao` e `parte_audio`.

Apagar uma consulta apaga em cascata as mensagens, os documentos SOAP, o
consentimento e as partes de audio pendentes (ON DELETE CASCADE no banco).
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
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


class MapaAnonimizacaoConsulta(Base):
    """Mapa token -> valor real de uma consulta, cifrado (B26 / US016-CA002).

    E o que torna os tokens ESTAVEIS POR CONSULTA (B25): sem persistir o
    mapa, cada requisicao recomecaria do `[CPF_1]` e o mesmo paciente teria
    tokens diferentes a cada mensagem.

    O conteudo e cifrado com a DEK do medico (AES-GCM), mesmo envelope da
    tabela `pseudonimo`. Linhas antigas com `algoritmo_cifra = "none"`
    guardam JSON em texto e sao recifradas na proxima escrita.
    """

    __tablename__ = "mapa_anonimizacao"

    # 1:1 com a consulta.
    consulta_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("consulta.id", ondelete="CASCADE"), primary_key=True
    )
    dados_cifrados: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    algoritmo_cifra: Mapped[str] = mapped_column(
        String(32), nullable=False, default="none"
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ParteAudio(UuidPkMixin, CriadoEmMixin, Base):
    """Parte (chunk) de audio de uma gravacao, aguardando a transcricao
    (B30 / US017-CA003).

    O audio NAO fica no banco: `caminho` aponta para um arquivo temporario do
    servidor, apagado junto com a linha quando a gravacao e transcrita
    (US017-CA007). `(consulta, gravacao, seq)` e unico: reenviar a mesma parte
    substitui a anterior em vez de duplicar.
    """

    __tablename__ = "parte_audio"
    __table_args__ = (UniqueConstraint("consulta_id", "gravacao_id", "seq"),)

    consulta_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("consulta.id", ondelete="CASCADE"), nullable=False
    )
    # Gerado pela extensao a cada gravacao: uma consulta pode ter varias.
    gravacao_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Posicao da parte na gravacao, a partir de 1.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    caminho: Mapped[str] = mapped_column(Text, nullable=False)
    tamanho_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Lida do cabecalho do WAV no servidor, nao informada pelo cliente.
    duracao_s: Mapped[float] = mapped_column(Float, nullable=False)
