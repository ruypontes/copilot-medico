
"""B45 - exportacao SOAP em PDF e Markdown."""
import io

import pytest

from backend import auth_decorators
from ids import DOCTOR_A, DOCTOR_B
from repositories import (
    ConsultaRepository,
    DocumentoSoapRepository,
    PacienteRepository,
    sessao,
)

VERSAO_IA = {
    "subjetivo": "Paciente [PACIENTE] relata febre.",
    "objetivo": "Temperatura 38,9 C.",
    "avaliacao": "Suspeita de dengue.",
    "plano": "Hidratacao e retorno em 48 horas.",
    "hipoteses": [
        {"descricao": "Dengue", "cid10": "A90", "confianca": "alta"}
    ],
    "alertas": ["Observar sinais de alarme."],
    "pendencias": ["Hemograma"],
}


def _login(monkeypatch, user_id=DOCTOR_A, profile="medico"):
    def fake(token):
        if token != "valid-token":
            raise auth_decorators.AuthError("Token invalido", 401)
        return (
            {
                "id": user_id,
                "email": "u@example.com",
                "name": "U",
                "profiles": [profile],
                "active": True,
            },
            {"profile": profile},
        )

    monkeypatch.setattr(auth_decorators, "get_user_from_token", fake)
    return {"Authorization": "Bearer valid-token"}


@pytest.fixture()
def medico(monkeypatch):
    return _login(monkeypatch)


@pytest.fixture()
def consulta(client):
    pid = PacienteRepository(
        sessao.obter_sessao()
    ).criar(nome="Paciente Exportacao", medico_id=DOCTOR_A)["id"]
    return ConsultaRepository(sessao.obter_sessao()).criar(
        pid, "Consulta exportacao"
    )


@pytest.fixture()
def soap(consulta):
    documento = DocumentoSoapRepository(
        sessao.obter_sessao()
    ).criar(consulta, VERSAO_IA)
    return consulta, documento["id"]


def _url(cid):
    return f"/api/consultations/{cid}/soap/export"


def test_exporta_markdown_por_padrao_anonimizado(client, medico, soap):
    cid, _sid = soap

    resp = client.get(_url(cid), headers=medico)

    assert resp.status_code == 200
    assert "text/markdown" in resp.content_type
    assert "[PACIENTE]" in resp.get_data(as_text=True)
    assert "Paciente Exportacao" not in resp.get_data(as_text=True)
    assert "## Subjetivo" in resp.get_data(as_text=True)


def test_exporta_pdf(client, medico, soap):
    cid, _sid = soap

    resp = client.get(
        _url(cid) + "?format=pdf",
        headers=medico,
    )

    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF")


def test_formato_invalido_retorna_400(client, medico, soap):
    cid, _sid = soap

    resp = client.get(
        _url(cid) + "?format=docx",
        headers=medico,
    )

    assert resp.status_code == 400


def test_consulta_sem_soap_retorna_404(client, medico, consulta):
    resp = client.get(_url(consulta), headers=medico)

    assert resp.status_code == 404


def test_exportacao_exige_token(client, soap):
    cid, _sid = soap

    resp = client.get(_url(cid))

    assert resp.status_code == 401


def test_outro_medico_nao_exporta_consulta(client, soap, monkeypatch):
    cid, _sid = soap
    outro = _login(monkeypatch, user_id=DOCTOR_B)

    resp = client.get(_url(cid), headers=outro)

    assert resp.status_code == 403


def test_exporta_versao_editada_pelo_medico(client, medico, soap):
    cid, sid = soap
    editada = {
        **VERSAO_IA,
        "plano": "Retorno em 24 horas.",
    }
    DocumentoSoapRepository(
        sessao.obter_sessao()
    ).salvar_edicao(sid, editada)

    resp = client.get(_url(cid), headers=medico)

    assert resp.status_code == 200
    assert "Retorno em 24 horas." in resp.get_data(as_text=True)
    assert "retorno em 48 horas." not in resp.get_data(as_text=True)
