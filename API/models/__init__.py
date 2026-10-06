"""Modelos SQLAlchemy do CoPilot Medico (B19 / US015 / ADR-02).

Importar este pacote registra todas as tabelas em `Base.metadata`, que e o
que o Alembic usa para gerar e conferir as migracoes (ver migrations/).
"""
from .base import Base
from .consulta import Consentimento, Consulta, DocumentoSoap, Mensagem
from .enums import OrigemPep, PapelMensagem, StatusAprovacao, StatusSoap, TipoConsentimento
from .medico import Medico
from .paciente import ALGORITMO_SEM_CIFRA, Paciente, Pseudonimo
from .registro import DadoExtensao, Transcricao
from .session import create_db_engine, make_session_factory

__all__ = [
    "ALGORITMO_SEM_CIFRA",
    "Base",
    "Consentimento",
    "Consulta",
    "DadoExtensao",
    "DocumentoSoap",
    "Medico",
    "Mensagem",
    "OrigemPep",
    "Paciente",
    "PapelMensagem",
    "Pseudonimo",
    "StatusAprovacao",
    "StatusSoap",
    "TipoConsentimento",
    "Transcricao",
    "create_db_engine",
    "make_session_factory",
]
