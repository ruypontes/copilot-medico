"""Cofres abertos durante a sessao do medico (B26 / ADR-03).

A chave de dados (DEK) so existe desembrulhada enquanto o medico esta logado:
ela e reconstruida no login, a partir da senha, e vive aqui em memoria ate o
logout ou o fim do processo.

Isso e uma consequencia direta de "chave derivada da senha", nao um atalho:
o servidor nao guarda a senha, entao nao ha como refazer a KEK sozinho.
Reiniciar o backend exige novo login para voltar a decifrar - e o preco de
nao deixar a chave em disco ao lado do dado cifrado.

Sem cofre aberto o sistema NAO quebra: a camada regex continua protegendo o
payload que vai ao LLM, e o que depende de decifrar (nome do paciente, mapa
da consulta) degrada para o pseudonimo.
"""
from __future__ import annotations

import threading

from .cripto import Cofre

# token de sessao -> cofre. Protegido por lock: o Flask atende requisicoes
# em threads e o dict pode ser lido e escrito ao mesmo tempo.
_cofres: dict[str, Cofre] = {}
_trava = threading.Lock()


def guardar(chave_sessao: str, cofre: Cofre) -> None:
    if not chave_sessao:
        return
    with _trava:
        _cofres[chave_sessao] = cofre


def obter(chave_sessao: str | None) -> Cofre | None:
    if not chave_sessao:
        return None
    with _trava:
        return _cofres.get(chave_sessao)


def descartar(chave_sessao: str | None) -> None:
    """Logout: a DEK sai da memoria."""
    if not chave_sessao:
        return
    with _trava:
        _cofres.pop(chave_sessao, None)


def limpar() -> None:
    """Usado pelos testes e no encerramento."""
    with _trava:
        _cofres.clear()


def total_aberto() -> int:
    with _trava:
        return len(_cofres)
