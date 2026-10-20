"""Geracao do SOAP pela IA (B40 / US018 / ADR-05).

O modelo recebe o prompt versionado (prompts/soap_v1.txt), o material da
consulta ja anonimizado e o `response_schema` do SoapV1. A resposta passa
por duas checagens:

1. o esquema (validar_soap, B39);
2. o conteudo: sem referencias/links e sem probabilidade em percentual
   (US018-CA002 / D-07) - o modelo as vezes inclui mesmo sendo pedido que nao.

Se falhar, ha UMA nova tentativa com a lista do que estava errado; se falhar
de novo, SoapNaoGerado. Erros da chamada ao modelo (cota, rede) sobem como
estao: quem chama decide a resposta HTTP.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .schema import SECOES, SoapInvalido, SoapV1, response_schema, validar_soap

PROMPT_ID = "soap"
PROMPT_VERSAO = "1"
INSTRUCAO = (Path(__file__).with_name("prompts") / f"soap_v{PROMPT_VERSAO}.txt").read_text(encoding="utf-8")

MAX_TENTATIVAS = 2  # a primeira + 1 retry (B40)

# Referencias: links, DOI, PubMed. Vale para qualquer texto do SOAP.
_REFERENCIA = re.compile(r"https?://|www\.|\bdoi\b\s*:?|pubmed|et al\.", re.IGNORECASE)
# Percentual so e proibido como probabilidade/confianca: a palavra e o numero
# na mesma frase. "Provavel IVAS; SatO2 96%" e medida clinica e continua valido.
_PALAVRA_PROB = r"(?:probabilidade|chances?|prov[aá]vel|certeza|confian[cç]a)"
_PCT = r"\d+(?:[.,]\d+)?\s*%"
_MESMA_FRASE = r"[^.;\n]{0,40}"
_PROBABILIDADE_PCT = re.compile(
    f"{_PALAVRA_PROB}{_MESMA_FRASE}{_PCT}|{_PCT}{_MESMA_FRASE}{_PALAVRA_PROB}", re.IGNORECASE
)
_PERCENTUAL = re.compile(_PCT)

ChamarModelo = Callable[[str, str, dict], str]


class SoapNaoGerado(Exception):
    """O modelo nao produziu um SOAP valido nem na nova tentativa."""

    def __init__(self, erros: list[str], tentativas: int):
        super().__init__("Nao foi possivel gerar um SOAP valido: " + "; ".join(erros))
        self.erros = erros
        self.tentativas = tentativas


@dataclass(frozen=True)
class ResultadoSoap:
    soap: SoapV1
    tentativas: int


def verificar_conteudo(soap: SoapV1) -> list[str]:
    """Regras de conteudo que o esquema nao expressa (US018-CA002)."""
    erros = []
    textos = {secao: getattr(soap, secao) for secao in SECOES}
    textos.update({f"hipoteses.{i}.descricao": h.descricao for i, h in enumerate(soap.hipoteses)})
    textos.update({f"alertas.{i}": t for i, t in enumerate(soap.alertas)})
    textos.update({f"pendencias.{i}": t for i, t in enumerate(soap.pendencias)})

    for campo, texto in textos.items():
        if _REFERENCIA.search(texto):
            erros.append(f"{campo}: nao cite referencias, DOIs nem links")
        if _PROBABILIDADE_PCT.search(texto) or (campo.startswith("hipoteses") and _PERCENTUAL.search(texto)):
            erros.append(f"{campo}: nao use percentual para probabilidade; a confianca e baixa/media/alta")
    return erros


def _pedido_de_correcao(material: str, erros: list[str]) -> str:
    lista = "\n".join(f"- {erro}" for erro in erros)
    return (
        f"{material}\n\n"
        "ATENÇÃO: a sua resposta anterior foi rejeitada pelos motivos abaixo. "
        "Gere o SOAP novamente, corrigindo todos eles, e responda apenas com o JSON.\n"
        f"{lista}"
    )


def gerar_soap(material: str, chamar_modelo: ChamarModelo) -> ResultadoSoap:
    """Gera e valida o SOAP. `chamar_modelo(instrucao, conteudo, schema)`
    devolve o texto da resposta do modelo."""
    if not material or not material.strip():
        raise ValueError("Material da consulta vazio: nada para gerar o SOAP.")

    conteudo, erros = material, []
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        resposta = chamar_modelo(INSTRUCAO, conteudo, response_schema())
        try:
            soap = validar_soap(resposta)
            erros = verificar_conteudo(soap)
        except SoapInvalido as erro:
            erros = erro.erros
        if not erros:
            return ResultadoSoap(soap=soap, tentativas=tentativa)
        conteudo = _pedido_de_correcao(material, erros)
    raise SoapNaoGerado(erros, MAX_TENTATIVAS)
