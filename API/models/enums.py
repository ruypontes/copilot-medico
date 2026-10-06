"""Valores fixos gravados no banco.

Os status de aprovacao mantem os valores em ingles que o auth_service e o
users_db.json ja usam, para que o B20/B21 nao precisem traduzir dados.
"""
import enum


class StatusAprovacao(str, enum.Enum):
    PENDENTE = "pending"
    APROVADO = "approved"
    REJEITADO = "rejected"


class PapelMensagem(str, enum.Enum):
    USUARIO = "user"
    MODELO = "model"


class OrigemPep(str, enum.Enum):
    AMPLIMED = "amplimed"
    ESUS_PEC = "esus_pec"
    MANUAL = "manual"


class StatusSoap(str, enum.Enum):
    GERADO = "gerado"
    EDITADO = "editado"
    APROVADO = "aprovado"
    INSERIDO_NO_PEP = "inserido_no_pep"


class TipoConsentimento(str, enum.Enum):
    VERBAL = "verbal"
    TERMO = "termo"
