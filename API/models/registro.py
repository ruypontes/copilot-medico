"""Registros do paciente que podem ou nao estar ligados a uma consulta:
`transcricao` e `dado_extensao`.

No patients_db.json os dois ficam no paciente, com consultation_id opcional
(`transcription_log` e `extension_data`), por isso `consulta_id` e nulo
aqui. Se a consulta for apagada, o registro continua no paciente.

`dado_extensao` nao esta no diagrama do doc 05; foi incluida no B19 para
que o B21 migre o extension_data existente sem perda.
"""
import uuid

from sqlalchemy import JSON, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CriadoEmMixin, UuidPkMixin


class Transcricao(UuidPkMixin, CriadoEmMixin, Base):
    __tablename__ = "transcricao"

    paciente_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("paciente.id", ondelete="CASCADE"), nullable=False, index=True
    )
    consulta_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("consulta.id", ondelete="SET NULL"), index=True
    )
    # [{papel, inicio, fim, texto}] - o "dialogue" do formato atual.
    turnos: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    # Texto corrido (o "text" atual), usado quando nao ha turnos.
    texto: Mapped[str | None] = mapped_column(Text)
    provedor: Mapped[str | None] = mapped_column(String(64))
    duracao_s: Mapped[float | None] = mapped_column(Float)
    wer_estimado: Mapped[float | None] = mapped_column(Float)
    metadados_audio: Mapped[dict | None] = mapped_column(JSON)


class DadoExtensao(UuidPkMixin, CriadoEmMixin, Base):
    __tablename__ = "dado_extensao"

    paciente_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("paciente.id", ondelete="CASCADE"), nullable=False, index=True
    )
    consulta_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("consulta.id", ondelete="SET NULL"), index=True
    )
    url_origem: Mapped[str | None] = mapped_column(Text)
    # Lista de {role, text}, objeto chave->valor ou texto, como a API aceita hoje.
    conteudo: Mapped[list | dict | str] = mapped_column(JSON, nullable=False)
    # B07: "extracted_data" (formato livre legado) ou "pep_import" (contrato
    # tipado), e o PEP de onde os campos vieram ("amplimed", "esus-pec", "outro").
    tipo: Mapped[str] = mapped_column(
        String(20), nullable=False, default="extracted_data", server_default="extracted_data"
    )
    pep_origem: Mapped[str | None] = mapped_column(String(20))
