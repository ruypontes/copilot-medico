"""SoapV1 PROVISORIO, so para o `run_eval.py` (B46).

A US018-CA001 define o esquema `SoapV1`; a B39 o implementa em `soap/schema.py`.
Ate la, o eval precisa de um contrato para medir "JSON valido", entao este
arquivo espelha o que esta escrito na US018:

    subjetivo, objetivo, avaliacao, plano       texto
    hipoteses[] {descricao, cid10, confianca: baixa|media|alta}
    alertas[], pendencias[]                      listas de texto

O `run_eval.py` tenta importar `soap.schema.SoapV1` primeiro; quando a B39 for
mesclada, o eval passa a usar o oficial sozinho e este arquivo pode ser apagado.
O relatorio diz qual dos dois foi usado.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Hipotese(BaseModel):
    model_config = ConfigDict(extra="forbid")

    descricao: str = Field(min_length=1)
    cid10: str = Field(min_length=1)
    confianca: Literal["baixa", "media", "alta"]


class SoapV1(BaseModel):
    # extra="forbid": uma chave inventada pelo modelo torna o JSON invalido.
    model_config = ConfigDict(extra="forbid")

    subjetivo: str = Field(min_length=1)
    objetivo: str = Field(min_length=1)
    avaliacao: str = Field(min_length=1)
    plano: str = Field(min_length=1)
    hipoteses: list[Hipotese] = Field(default_factory=list)
    alertas: list[str] = Field(default_factory=list)
    pendencias: list[str] = Field(default_factory=list)
