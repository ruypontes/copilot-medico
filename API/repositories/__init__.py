"""Camada de acesso a dados por entidade (B20 / US015).

Substitui o backend/patient_db.py (e o users_db.json do auth_service). Cada
repositorio recebe uma sessao SQLAlchemy; na aplicacao a sessao vem de
`sessao.obter_sessao()`, uma por requisicao.
"""
from . import sessao
from .anonimizacao import MapaAnonimizacaoRepository
from .consultas import ConsultaRepository, DocumentoSoapRepository, MensagemRepository
from .medicos import MedicoRepository
from .pacientes import MedicoNaoEncontrado, PacienteRepository
from .partes_audio import ParteAudioRepository
from .registros import DadoExtensaoRepository, TranscricaoRepository

__all__ = [
    "ConsultaRepository",
    "DadoExtensaoRepository",
    "DocumentoSoapRepository",
    "MapaAnonimizacaoRepository",
    "MedicoNaoEncontrado",
    "MedicoRepository",
    "MensagemRepository",
    "PacienteRepository",
    "ParteAudioRepository",
    "TranscricaoRepository",
    "sessao",
]
