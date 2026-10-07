"""Persistencia do mapa de anonimizacao por consulta (B26 / US016-CA002).

O mapa token -> valor real e PII concentrada: se vazar, desfaz toda a
anonimizacao de uma vez. Por isso ele vai cifrado com a DEK do medico
(AES-GCM), igual a tabela `pseudonimo`.

Sem cofre aberto o repositorio NAO grava em texto claro - prefere nao
persistir e perder a estabilidade dos tokens entre requisicoes a escrever
PII legivel no banco. A camada regex continua protegendo o payload externo.
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from backend.anonimizacao import MapaAnonimizacao
from backend.anonimizacao.cripto import (
    ALGORITMO,
    ALGORITMO_SEM_CIFRA,
    Cofre,
    FalhaAoDecifrar,
)
from models import MapaAnonimizacaoConsulta

from .base import Repositorio, parse_uuid


class MapaAnonimizacaoRepository(Repositorio):
    def _linha(self, consulta_id: uuid.UUID) -> MapaAnonimizacaoConsulta | None:
        return self.sessao.scalar(
            select(MapaAnonimizacaoConsulta).where(
                MapaAnonimizacaoConsulta.consulta_id == consulta_id
            )
        )

    def carregar(self, consulta_id: str, cofre: Cofre | None) -> MapaAnonimizacao:
        """Mapa da consulta; vazio se nao existir ou se nao der para decifrar."""
        identificador = parse_uuid(consulta_id)
        if identificador is None:
            return MapaAnonimizacao()

        linha = self._linha(identificador)
        if linha is None:
            return MapaAnonimizacao()

        # Linha legada (B19 gravava "none"): JSON em texto.
        if linha.algoritmo_cifra == ALGORITMO_SEM_CIFRA:
            try:
                return MapaAnonimizacao.de_dicionario(json.loads(linha.dados_cifrados))
            except (ValueError, TypeError):
                return MapaAnonimizacao()

        if cofre is None:
            # Sem a chave da sessao nao ha o que fazer: devolve vazio em vez
            # de estourar, e os tokens recomecam nesta requisicao.
            return MapaAnonimizacao()

        try:
            return MapaAnonimizacao.de_dicionario(cofre.decifrar_json(linha.dados_cifrados))
        except FalhaAoDecifrar:
            return MapaAnonimizacao()

    def salvar(self, consulta_id: str, mapa: MapaAnonimizacao, cofre: Cofre | None) -> bool:
        """Grava o mapa cifrado. Devolve False se nao houver cofre aberto."""
        identificador = parse_uuid(consulta_id)
        if identificador is None or cofre is None or not mapa:
            return False

        blob = cofre.cifrar_json(mapa.para_dicionario())
        linha = self._linha(identificador)
        if linha is None:
            linha = MapaAnonimizacaoConsulta(consulta_id=identificador)
            self.sessao.add(linha)
        linha.dados_cifrados = blob
        linha.algoritmo_cifra = ALGORITMO
        self.sessao.commit()
        return True

    def apagar(self, consulta_id: str) -> None:
        identificador = parse_uuid(consulta_id)
        if identificador is None:
            return
        linha = self._linha(identificador)
        if linha is not None:
            self.sessao.delete(linha)
            self.sessao.commit()
