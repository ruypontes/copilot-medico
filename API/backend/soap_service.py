import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class HipoteseSoap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    descricao: str = Field(min_length=1)
    cid10: str | None = None
    confianca: Literal["baixa", "media", "alta"]


class SoapV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subjetivo: str
    objetivo: str
    avaliacao: str
    plano: str
    hipoteses: list[HipoteseSoap] = Field(default_factory=list)
    alertas: list[str] = Field(default_factory=list)
    pendencias: list[str] = Field(default_factory=list)


class SoapGenerationError(Exception):
    pass


def validar_soap(payload: object) -> dict:
    try:
        return SoapV1.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        raise SoapGenerationError("O conteúdo SOAP não corresponde ao esquema SoapV1.") from exc


def gerar_soap(contexto: str) -> dict:
    import google.generativeai as genai

    from .config import settings

    if not settings.gemini_api_key:
        raise SoapGenerationError("GEMINI_API_KEY não está configurada.")

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config={"response_mime_type": "application/json"},
    )
    prompt = f"""Gere um registro clínico SOAP em português do Brasil usando somente os dados fornecidos.
Não invente informações. Use texto vazio quando uma seção não tiver dados suficientes.
Não inclua referências bibliográficas nem percentuais numéricos. A confiança de cada hipótese deve ser baixa, media ou alta.
Retorne somente um objeto JSON com as chaves subjetivo, objetivo, avaliacao, plano,
hipoteses (itens com descricao, cid10 e confianca), alertas e pendencias.

Dados da consulta:
{contexto}
"""
    try:
        response = model.generate_content(prompt)
        if not response.text:
            raise SoapGenerationError("O modelo não retornou um SOAP.")
        return validar_soap(json.loads(response.text))
    except SoapGenerationError:
        raise
    except (json.JSONDecodeError, ValidationError) as exc:
        raise SoapGenerationError("O modelo retornou um SOAP inválido.") from exc
    except Exception as exc:
        raise SoapGenerationError("Não foi possível gerar o SOAP.") from exc