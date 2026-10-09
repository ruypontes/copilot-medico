"""Auditoria de envios externos (B36 / US016-CA004).

Cada vez que algo sai da maquina para um provedor externo (LLM, servico de
transcricao), uma linha e gravada aqui: QUANDO, de QUAL consulta, para QUAL
provedor e QUANTO. O CONTEUDO nunca entra - nem texto, nem JSON, nem trecho
de erro. Por isso a tabela so tem colunas numericas, ids e rotulos curtos: um
log de auditoria que guarda o que enviou vira, ele mesmo, um vazamento.

`tests/test_b36_auditoria.py` falha se alguem acrescentar uma coluna de
texto livre ou JSON a esta tabela.

Retencao: 12 meses (docs/08-lgpd-seguranca.md). A limpeza periodica ainda nao
existe; a coluna `criado_em` ja permite o corte por data.
"""
import uuid

from sqlalchemy import ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CriadoEmMixin, UuidPkMixin


class EnvioExterno(UuidPkMixin, CriadoEmMixin, Base):
    __tablename__ = "envio_externo"

    # Nulos quando o envio nao esta ligado a uma consulta (ex.: audio enviado
    # sem consulta) ou quando a consulta/medico foram apagados depois: o
    # registro de que algo saiu precisa sobreviver a quem o originou.
    consulta_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("consulta.id", ondelete="SET NULL"), index=True
    )
    medico_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("medico.id", ondelete="SET NULL"), index=True
    )
    # "gemini", "google_sr", ... (rotulos em repositories/auditoria.py). String
    # e nao enum para que um provedor novo (S3) nao exija migracao.
    provedor: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # Para que serviu: "chat", "extensao", "pdf", "recomendacao", "transcricao".
    operacao: Mapped[str] = mapped_column(String(32), nullable=False)
    # Bytes UTF-8 do texto enviado (LLM) ou bytes de audio PCM (transcricao).
    tamanho_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Quantas chamadas ao provedor este registro resume. A transcricao envia um
    # trecho de audio por vez e e registrada uma vez por requisicao.
    chamadas: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
