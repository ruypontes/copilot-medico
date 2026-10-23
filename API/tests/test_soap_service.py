import json
from types import SimpleNamespace

import pytest

from backend import soap_service


SOAP_VALIDO = {
    "subjetivo": "Dor de cabeça há dois dias.",
    "objetivo": "Sem sinais vitais informados.",
    "avaliacao": "Cefaleia.",
    "plano": "Investigar evolução.",
    "hipoteses": [{"descricao": "Cefaleia", "cid10": "R51", "confianca": "media"}],
    "alertas": [],
    "pendencias": ["Aferir pressão arterial"],
}


def test_validar_soap_aceita_estrutura_completa():
    assert soap_service.validar_soap(SOAP_VALIDO) == SOAP_VALIDO


def test_validar_soap_rejeita_confianca_invalida():
    payload = {**SOAP_VALIDO, "hipoteses": [{"descricao": "Cefaleia", "confianca": "80%"}]}

    with pytest.raises(soap_service.SoapGenerationError):
        soap_service.validar_soap(payload)


def test_gerar_soap_solicita_json_e_valida_resposta(monkeypatch):
    import google.generativeai as genai

    chamada = {}

    class ModeloFalso:
        def __init__(self, **kwargs):
            chamada["config"] = kwargs

        def generate_content(self, prompt):
            chamada["prompt"] = prompt
            return SimpleNamespace(text=json.dumps(SOAP_VALIDO))

    monkeypatch.setattr(genai, "configure", lambda **_kwargs: None)
    monkeypatch.setattr(genai, "GenerativeModel", ModeloFalso)

    assert soap_service.gerar_soap("Paciente relata cefaleia.") == SOAP_VALIDO
    assert chamada["config"]["generation_config"]["response_mime_type"] == "application/json"
    assert "referências bibliográficas" in chamada["prompt"]