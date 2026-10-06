"""Ligacao entre o login e o cofre de cifra (B26 / ADR-03).

O cofre so pode ser aberto no momento em que a senha em claro passa pelo
servidor - ou seja, no login. Daqui em diante a senha e descartada e so a
DEK desembrulhada continua viva, em memoria, ate o logout.

Medicos cadastrados antes do B26 nao tem material de chave; o primeiro login
apos a atualizacao cria o envelope deles, sem migracao de dados.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Medico

from . import cofres
from .cripto import Cofre, FalhaAoDecifrar, abrir_cofre, criar_cofre
from .nucleo import MapaAnonimizacao


def abrir_ou_criar_cofre(sessao: Session, usuario_id, senha: str) -> Cofre | None:
    """Cofre do medico a partir da senha; cria o envelope na primeira vez.

    Devolve None (sem levantar) quando nao da para abrir: a aplicacao segue
    funcionando com a camada regex, que nao depende de chave nenhuma.
    """
    from repositories.base import parse_uuid

    identificador = parse_uuid(usuario_id)
    if identificador is None or not senha:
        return None

    medico = sessao.scalar(select(Medico).where(Medico.id == identificador))
    if medico is None:
        return None

    if medico.chave_cifrada and medico.chave_salt:
        try:
            return abrir_cofre(senha, medico.chave_cifrada, medico.chave_salt)
        except FalhaAoDecifrar:
            # Senha trocada por fora (ex.: reset administrativo) deixa a DEK
            # inacessivel. Nao recriamos o cofre aqui: isso tornaria
            # ilegiveis os dados ja cifrados sem deixar rastro.
            print(
                f"[ANONIMIZACAO] Chave de dados do medico {medico.id} nao abriu "
                "com esta senha; dados cifrados anteriores seguem inacessiveis."
            )
            return None

    # Primeiro login apos o B26: cria e guarda o envelope.
    cofre, dek_cifrada, salt = criar_cofre(senha)
    medico.chave_cifrada = dek_cifrada
    medico.chave_salt = salt
    sessao.commit()
    return cofre


def registrar_sessao(token: str, cofre: Cofre | None) -> None:
    if cofre is not None:
        cofres.guardar(token, cofre)


def encerrar_sessao(token: str | None) -> None:
    cofres.descartar(token)


def cofre_da_sessao(token: str | None) -> Cofre | None:
    return cofres.obter(token)


def nomes_do_cadastro(paciente: dict | None) -> list[str]:
    """Nomes que alimentam a camada NER (B26).

    Hoje e o nome do proprio paciente da consulta - a fonte mais confiavel
    que temos. Acompanhantes e profissionais citados ficam a cargo do NER.
    """
    if not isinstance(paciente, dict):
        return []
    nome = paciente.get("name") or paciente.get("nome")
    if not isinstance(nome, str) or not nome.strip():
        return []
    if nome.strip().lower() in {"desconhecido", "sem nome"}:
        return []
    partes = [nome.strip()]
    # Tambem o primeiro nome isolado: o medico costuma escrever so "Maria".
    primeiro = nome.strip().split()[0]
    if len(primeiro) >= 3 and primeiro.lower() != nome.strip().lower():
        partes.append(primeiro)
    return partes


__all__ = [
    "MapaAnonimizacao",
    "abrir_ou_criar_cofre",
    "cofre_da_sessao",
    "encerrar_sessao",
    "nomes_do_cadastro",
    "registrar_sessao",
]
