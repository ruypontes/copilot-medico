"""Anonimizacao em duas camadas (US016 / ADR-03).

Camada 1 (B25): padroes deterministicos por regex - CPF, RG, CNS, telefone,
e-mail, CEP e datas completas, com validacao de digito verificador.
Camada 2 (B26): NER spaCy (PER/LOC) + nomes vindos do cadastro de pacientes,
com lista de excecoes para nao mascarar doenca eponima.

Uso tipico no fluxo de uma mensagem:

    resultado = anonimizar(texto, mapa_da_consulta, nomes_do_cadastro)
    resposta = llm(resultado.texto)          # sai sem PII
    exibir(resultado.mapa.reidratar(resposta))  # volta com PII so na tela
"""
from typing import Any, Sequence

from .nucleo import MapaAnonimizacao, Resultado, anonimizar_regex
from .ner import (
    EXCECOES_MEDICAS,
    TIPO_LOCAL,
    TIPO_PESSOA,
    anonimizar_ner,
    carregar_nlp,
    e_excecao_medica,
)
from .padroes import (
    TIPO_CEP,
    TIPO_CNS,
    TIPO_CPF,
    TIPO_DATA,
    TIPO_EMAIL,
    TIPO_RG,
    TIPO_TELEFONE,
    valida_cns,
    valida_cpf,
)


def anonimizar(
    texto: str,
    mapa: MapaAnonimizacao | None = None,
    nomes_conhecidos: Sequence[str] = (),
    nlp: Any = None,
) -> Resultado:
    """Aplica as duas camadas e devolve texto sem PII + mapa para a volta.

    A ordem importa: o regex roda primeiro porque e deterministico e ja
    retira os blocos numericos. Rodar o NER antes faria o spaCy tropecar em
    CPF e telefone, que ele as vezes rotula como entidade.
    """
    resultado = anonimizar_regex(texto, mapa)
    return anonimizar_ner(
        resultado.texto,
        resultado.mapa,
        nomes_conhecidos=nomes_conhecidos,
        nlp=nlp,
    )


__all__ = [
    "EXCECOES_MEDICAS",
    "MapaAnonimizacao",
    "Resultado",
    "TIPO_CEP",
    "TIPO_CNS",
    "TIPO_CPF",
    "TIPO_DATA",
    "TIPO_EMAIL",
    "TIPO_LOCAL",
    "TIPO_PESSOA",
    "TIPO_RG",
    "TIPO_TELEFONE",
    "anonimizar",
    "anonimizar_ner",
    "anonimizar_regex",
    "carregar_nlp",
    "e_excecao_medica",
    "valida_cns",
    "valida_cpf",
]
