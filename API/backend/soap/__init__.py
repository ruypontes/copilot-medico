"""SOAP estruturado da consulta (Epico SOAP, US018)."""
from .schema import (
    SECOES,
    VERSAO,
    Confianca,
    Hipotese,
    SoapInvalido,
    SoapV1,
    response_schema,
    validar_soap,
)

__all__ = [
    "SECOES",
    "VERSAO",
    "Confianca",
    "Hipotese",
    "SoapInvalido",
    "SoapV1",
    "response_schema",
    "validar_soap",
]
