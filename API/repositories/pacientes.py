"""Repositorio de `paciente` + `pseudonimo`.

O nome nao fica em `paciente` (US015-CA004): vai para `pseudonimo`,
cifrado com a chave do medico quando ha cofre aberto (B26 / ADR-03). Para a
API o paciente continua saindo como {id, name, doctor_id, created_by,
created_at}.

Sem cofre o repositorio continua lendo e gravando o formato legado
(`algoritmo_cifra = "none"`, JSON em texto). Isso mantem compativel tudo que
foi gravado pelo B19 e permite que rotas administrativas sem sessao de
medico sigam funcionando - a mudanca e progressiva, nao um corte.
"""
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.anonimizacao.cripto import ALGORITMO, Cofre, FalhaAoDecifrar
from models import ALGORITMO_SEM_CIFRA, Medico, Paciente, Pseudonimo

from .base import Repositorio, id_texto, iso, parse_uuid

NOME_PADRAO = "Desconhecido"


class MedicoNaoEncontrado(ValueError):
    pass


def _nome(paciente: Paciente, cofre: Cofre | None = None) -> str:
    dados = paciente.dados_identificaveis
    if dados is None:
        return NOME_PADRAO

    # Linha legada do B19: JSON em texto.
    if dados.algoritmo_cifra == ALGORITMO_SEM_CIFRA:
        try:
            return json.loads(dados.dados_cifrados).get("nome") or NOME_PADRAO
        except (ValueError, TypeError):
            return NOME_PADRAO

    if cofre is None:
        # Cifrado e sem chave na sessao: devolve o pseudonimo em vez do nome.
        # Degradar e correto aqui - inventar "Desconhecido" esconderia do
        # medico que existe um nome que ele nao consegue abrir.
        return paciente.pseudonimo or NOME_PADRAO

    try:
        return cofre.decifrar_json(dados.dados_cifrados).get("nome") or NOME_PADRAO
    except FalhaAoDecifrar:
        return paciente.pseudonimo or NOME_PADRAO


def para_dicionario(paciente: Paciente, cofre: Cofre | None = None) -> dict:
    return {
        "id": id_texto(paciente.id),
        "name": _nome(paciente, cofre),
        "doctor_id": id_texto(paciente.medico_id),
        "created_by": id_texto(paciente.criado_por_id),
        "created_at": iso(paciente.criado_em),
    }


def novo_pseudonimo(paciente_id: uuid.UUID) -> str:
    return f"PAC-{paciente_id.hex[:12].upper()}"


class PacienteRepository(Repositorio):
    def __init__(self, sessao, cofre: Cofre | None = None):
        """`cofre` vem da sessao do medico (B26); sem ele o repositorio
        opera no formato legado, sem cifra."""
        super().__init__(sessao)
        self.cofre = cofre

    def _consulta_base(self):
        return select(Paciente).options(selectinload(Paciente.dados_identificaveis))

    def obter_modelo(self, paciente_id) -> Paciente | None:
        pid = parse_uuid(paciente_id)
        if pid is None:
            return None
        return self.sessao.scalar(self._consulta_base().where(Paciente.id == pid))

    def obter(self, paciente_id) -> dict | None:
        paciente = self.obter_modelo(paciente_id)
        return para_dicionario(paciente, self.cofre) if paciente else None

    def listar(self, medico_id=None) -> list[dict]:
        """Sem `medico_id`: todos (visao do admin). Com: so os desse medico."""
        consulta = self._consulta_base().order_by(Paciente.criado_em)
        if medico_id is not None:
            mid = parse_uuid(medico_id)
            if mid is None:
                return []
            consulta = consulta.where(Paciente.medico_id == mid)
        return [para_dicionario(p, self.cofre) for p in self.sessao.scalars(consulta)]

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
        paciente.dados_identificaveis = Pseudonimo(**self._dados_identificaveis(nome))
        self.sessao.add(paciente)
        self.sessao.commit()
        return para_dicionario(paciente)

    def _dados_identificaveis(self, nome) -> dict:
        """Serializa o bloco identificavel, cifrado se houver cofre (B26).

        Sem cofre grava no formato legado para nao criar uma linha que o
        proprio sistema nao conseguiria reabrir depois.
        """
        conteudo = {"nome": nome or NOME_PADRAO}
        if self.cofre is not None:
            return {
                "dados_cifrados": self.cofre.cifrar_json(conteudo),
                "algoritmo_cifra": ALGORITMO,
            }
        return {
            "dados_cifrados": json.dumps(conteudo).encode("utf-8"),
            "algoritmo_cifra": ALGORITMO_SEM_CIFRA,
        }
