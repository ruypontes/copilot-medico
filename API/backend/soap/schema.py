"""Esquema SoapV1: o SOAP estruturado da consulta (B39 / US018-CA001 / ADR-05).

Todo SOAP - o gerado pela IA (B40) e o editado pelo medico (B43) - passa por
aqui antes de ser gravado em `documento_soap`. JSON fora do esquema e
rejeitado com a lista do que esta errado, em vez de virar texto livre.

    subjetivo, objetivo, avaliacao, plano   texto, obrigatorios
    hipoteses[]  {descricao, cid10, confianca: baixa|media|alta}
    alertas[]    sinais de alarme
    pendencias[] o que faltou perguntar ou examinar

A confianca e qualitativa (US018-CA002 / decisao P8): nao ha percentuais.
"""
from __future__ import annotations

import enum
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

VERSAO = "SoapV1"
SECOES = ("subjetivo", "objetivo", "avaliacao", "plano")

# CID-10: letra + 2 digitos, subcategoria opcional (G44, G44.2, I10, U07.1).
# Aceita sem o ponto ("G442") e em minusculas, e devolve normalizado.
_CID10 = re.compile(r"^([A-Z])(\d{2})\.?(\d{1,2})?$")


class Confianca(str, enum.Enum):
    BAIXA = "baixa"
    MEDIA = "media"
    ALTA = "alta"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Hipotese(_Base):
    descricao: str = Field(min_length=3, max_length=300)
    cid10: str | None = None
    confianca: Confianca

    @field_validator("cid10", mode="before")
    @classmethod
    def _normalizar_cid10(cls, valor: Any) -> str | None:
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            return None
        if not isinstance(valor, str):
            raise ValueError("cid10 deve ser texto, ex.: G44.2")
        casamento = _CID10.match(valor.strip().upper())
        if not casamento:
            raise ValueError(f"cid10 invalido: {valor!r} (formato esperado: letra + 2 digitos, ex.: G44.2)")
        letra, categoria, subcategoria = casamento.groups()
        return f"{letra}{categoria}" + (f".{subcategoria}" if subcategoria else "")

    @field_validator("confianca", mode="before")
    @classmethod
    def _confianca_sem_acento(cls, valor: Any) -> Any:
        # O modelo as vezes escreve "média"; o valor gravado e sempre "media".
        return valor.strip().lower().replace("é", "e") if isinstance(valor, str) else valor



class SoapV1(_Base):
    subjetivo: str = Field(min_length=1)
    objetivo: str = Field(min_length=1)
    avaliacao: str = Field(min_length=1)
    plano: str = Field(min_length=1)
    hipoteses: list[Hipotese] = Field(default_factory=list, max_length=10)
    alertas: list[str] = Field(default_factory=list, max_length=20)
    pendencias: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("alertas", "pendencias", mode="after")
    @classmethod
    def _sem_itens_vazios(cls, itens: list[str]) -> list[str]:
        if any(not item for item in itens):
            raise ValueError("itens da lista nao podem ser vazios")
        return itens


class SoapInvalido(ValueError):
    """JSON que nao segue o SoapV1; `erros` diz campo a campo o que falhou."""

    def __init__(self, erros: list[str]):
        super().__init__("SOAP invalido: " + "; ".join(erros))
        self.erros = erros


_MENSAGENS = {
    "extra_forbidden": "campo nao faz parte do SoapV1",
    "missing": "obrigatorio",
    "string_too_short": "nao pode ser vazio (ou e curto demais)",
    "string_too_long": "texto longo demais",
    "too_long": "itens demais na lista",
    "string_type": "deve ser texto",
    "list_type": "deve ser uma lista",
    "model_type": "deve ser um objeto",
    "dict_type": "deve ser um objeto",
}


def _descrever(erro: dict) -> str:
    campo = ".".join(str(parte) for parte in erro["loc"]) or "(raiz)"
    tipo = erro["type"]
    if tipo == "enum":
        return f"{campo}: use um de: {', '.join(c.value for c in Confianca)}"
    if tipo == "value_error":
        return f"{campo}: {erro['msg'].removeprefix('Value error, ')}"
    return f"{campo}: {_MENSAGENS.get(tipo, erro['msg'])}"


def validar_soap(dados: dict | str | bytes) -> SoapV1:
    """Valida um SOAP (objeto ou texto JSON) e devolve o SoapV1 normalizado.

    Levanta SoapInvalido para JSON malformado ou fora do esquema.
    """
    if isinstance(dados, (str, bytes)):
        try:
            dados = json.loads(dados)
        except ValueError as erro:
            raise SoapInvalido([f"(raiz): JSON malformado ({erro})"]) from None
    if not isinstance(dados, dict):
        raise SoapInvalido(["(raiz): o SOAP deve ser um objeto JSON"])
    try:
        return SoapV1.model_validate(dados)
    except ValidationError as erro:
        raise SoapInvalido([_descrever(e) for e in erro.errors()]) from None


def response_schema() -> dict:
    """SoapV1 no subconjunto de OpenAPI aceito pelo `response_schema` do
    Gemini (ADR-05): sem $ref, pattern nem additionalProperties. A validacao
    completa continua sendo `validar_soap` sobre a resposta."""
    texto = {"type": "string"}
    lista_de_texto = {"type": "array", "items": texto}
    return {
        "type": "object",
        "properties": {
            **{secao: texto for secao in SECOES},
            "hipoteses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "descricao": texto,
                        "cid10": texto,
                        "confianca": {"type": "string", "enum": [c.value for c in Confianca]},
                    },
                    "required": ["descricao", "confianca"],
                },
            },
            "alertas": lista_de_texto,
            "pendencias": lista_de_texto,
        },
        "required": [*SECOES, "hipoteses", "alertas", "pendencias"],
    }
