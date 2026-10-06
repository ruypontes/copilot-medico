"""Repositorio de `paciente` + `pseudonimo`.

O nome nao fica em `paciente` (US015-CA004): vai para `pseudonimo`, ainda
sem cifra ate o B26 (ver models/paciente.py). Para a API o paciente continua
saindo como {id, name, doctor_id, created_by, created_at}.
"""
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from models import ALGORITMO_SEM_CIFRA, Medico, Paciente, Pseudonimo

from .base import Repositorio, id_texto, iso, parse_uuid

NOME_PADRAO = "Desconhecido"


class MedicoNaoEncontrado(ValueError):
    pass


def _nome(paciente: Paciente) -> str:
    dados = paciente.dados_identificaveis
    if dados is None:
        return NOME_PADRAO
    # Com cifra (B26) este e o ponto onde a decifragem entra.
    if dados.algoritmo_cifra == ALGORITMO_SEM_CIFRA:
        return json.loads(dados.dados_cifrados).get("nome") or NOME_PADRAO
    return NOME_PADRAO


def para_dicionario(paciente: Paciente) -> dict:
    return {
        "id": id_texto(paciente.id),
        "name": _nome(paciente),
        "doctor_id": id_texto(paciente.medico_id),
        "created_by": id_texto(paciente.criado_por_id),
        "created_at": iso(paciente.criado_em),
    }


def novo_pseudonimo(paciente_id: uuid.UUID) -> str:
    return f"PAC-{paciente_id.hex[:12].upper()}"


class PacienteRepository(Repositorio):
    def _consulta_base(self):
        return select(Paciente).options(selectinload(Paciente.dados_identificaveis))

    def obter_modelo(self, paciente_id) -> Paciente | None:
        pid = parse_uuid(paciente_id)
        if pid is None:
            return None
        return self.sessao.scalar(self._consulta_base().where(Paciente.id == pid))

    def obter(self, paciente_id) -> dict | None:
        paciente = self.obter_modelo(paciente_id)
        return para_dicionario(paciente) if paciente else None

    def listar(self, medico_id=None) -> list[dict]:
        """Sem `medico_id`: todos (visao do admin). Com: so os desse medico."""
        consulta = self._consulta_base().order_by(Paciente.criado_em)
        if medico_id is not None:
            mid = parse_uuid(medico_id)
            if mid is None:
                return []
            consulta = consulta.where(Paciente.medico_id == mid)
        return [para_dicionario(p) for p in self.sessao.scalars(consulta)]

    def atribuir_medico_aos_sem_medico(self, medico_id, simular=False) -> list[str]:
        """D-24 / B68: pacientes sem medico ficam invisiveis para todos os
        medicos. Atribui `medico_id` a todos eles e devolve os IDs.

        Idempotente (rodar de novo nao muda nada). Com `simular=True` so
        calcula o resultado, sem gravar.
        """
        mid = parse_uuid(medico_id)
        if mid is None or self.sessao.get(Medico, mid) is None:
            raise MedicoNaoEncontrado("Medico responsavel nao encontrado.")
        sem_medico = list(self.sessao.scalars(
            select(Paciente).where(Paciente.medico_id.is_(None)).order_by(Paciente.criado_em)
        ))
        if not simular:
            for paciente in sem_medico:
                paciente.medico_id = mid
            self.sessao.commit()
        return [id_texto(p.id) for p in sem_medico]

    def criar(self, nome=None, medico_id=None, criado_por_id=None) -> dict:
        medico = None
        if medico_id is not None:
            medico = self.sessao.get(Medico, parse_uuid(medico_id)) if parse_uuid(medico_id) else None
            if medico is None:
                raise MedicoNaoEncontrado("Medico responsavel nao encontrado.")
        criador_id = parse_uuid(criado_por_id)
        if criador_id is not None and self.sessao.get(Medico, criador_id) is None:
            criador_id = None

        paciente = Paciente(id=uuid.uuid4(), medico_id=medico.id if medico else None,
                            criado_por_id=criador_id)
        paciente.pseudonimo = novo_pseudonimo(paciente.id)
        paciente.dados_identificaveis = Pseudonimo(
            dados_cifrados=json.dumps({"nome": nome or NOME_PADRAO}).encode("utf-8"),
            algoritmo_cifra=ALGORITMO_SEM_CIFRA,
        )
        self.sessao.add(paciente)
        self.sessao.commit()
        return para_dicionario(paciente)
