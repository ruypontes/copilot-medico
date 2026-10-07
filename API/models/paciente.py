"""Tabelas `paciente` e `pseudonimo` (US015-CA004).

`paciente` nao guarda nome nem documentos: so o pseudonimo e dados
demograficos minimos. O que identifica a pessoa fica em `pseudonimo`.

Decisao do B19: ate o B26 implementar a cifragem com chave do medico,
`pseudonimo.dados_cifrados` guarda o JSON {"nome": ...} em texto e
`algoritmo_cifra` vale "none". O B26 so liga a cifra e regrava as linhas
cujo algoritmo ainda e "none" - sem mudanca de esquema.
"""
import uuid

from sqlalchemy import CHAR, ForeignKey, Integer, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CriadoEmMixin, UuidPkMixin

ALGORITMO_SEM_CIFRA = "none"


class Paciente(UuidPkMixin, CriadoEmMixin, Base):
    __tablename__ = "paciente"

    # Nulo quando o paciente foi criado por um administrador sem medico
    # responsavel (mesmo comportamento do patients_db.json; ver D-24).
    medico_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("medico.id", ondelete="RESTRICT"), index=True
    )
    criado_por_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("medico.id", ondelete="SET NULL")
    )
    pseudonimo: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    sexo: Mapped[str | None] = mapped_column(CHAR(1))
    ano_nascimento: Mapped[int | None] = mapped_column(Integer)

    dados_identificaveis: Mapped["Pseudonimo | None"] = relationship(
        back_populates="paciente", cascade="all, delete-orphan", uselist=False
    )


class Pseudonimo(Base):
    __tablename__ = "pseudonimo"

    paciente_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("paciente.id", ondelete="CASCADE"), primary_key=True
    )
    # Nome, CPF, telefone... serializados. Ver a nota do modulo sobre a cifra.
    dados_cifrados: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    algoritmo_cifra: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ALGORITMO_SEM_CIFRA
    )

    paciente: Mapped[Paciente] = relationship(back_populates="dados_identificaveis")
