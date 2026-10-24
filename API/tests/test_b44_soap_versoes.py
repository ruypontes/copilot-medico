"""B44 - versoes IA e medico do SOAP com diff (US018).

Criterio de aceite: diff visivel apos edicao. O documento e gravado pelo
DocumentoSoapRepository do B39 (sempre validado pelo SoapV1); aqui entram o
diff por secao (palavra no texto, item nas listas) e as rotas que a extensao
usa para ler e editar.
"""
import runpy
import uuid
from pathlib import Path

import pytest

from backend import auth_decorators
from backend.soap.diff import calcular_diff
from ids import DOCTOR_A, DOCTOR_B
from models import DocumentoSoap
from repositories import ConsultaRepository, DocumentoSoapRepository, PacienteRepository, sessao

VERSAO_IA = {
    "subjetivo": "Febre há três dias, dor no corpo.",
    "objetivo": "Temperatura 38,9 °C.",
    "avaliacao": "Provável dengue sem sinais de alarme.",
    "plano": "Hidratação oral e retorno em 48 horas.",
    "hipoteses": [{"descricao": "Dengue", "cid10": "A90", "confianca": "alta"}],
    "alertas": [],
    "pendencias": ["Hemograma"],
}


def _login(monkeypatch, user_id=DOCTOR_A, profile="medico"):
    def fake(token):
        if token != "valid-token":
            raise auth_decorators.AuthError("Token invalido", 401)
        return ({"id": user_id, "email": "u@example.com", "name": "U", "profiles": [profile],
                 "active": True}, {"profile": profile})

    monkeypatch.setattr(auth_decorators, "get_user_from_token", fake)
    return {"Authorization": "Bearer valid-token"}


@pytest.fixture()
def medico(monkeypatch):
    return _login(monkeypatch)


@pytest.fixture()
def consulta(client):
    pid = PacienteRepository(sessao.obter_sessao()).criar(nome="Paciente SOAP", medico_id=DOCTOR_A)["id"]
    return ConsultaRepository(sessao.obter_sessao()).criar(pid, "Consulta SOAP")


@pytest.fixture()
def soap(consulta):
    """(consulta, id do SOAP) recem-gerado pela IA."""
    return consulta, DocumentoSoapRepository(sessao.obter_sessao()).criar(consulta, VERSAO_IA)["id"]


def _editado(**mudancas):
    return {**VERSAO_IA, **mudancas}


def _secao(diff, nome):
    return next(s for s in diff["secoes"] if s["secao"] == nome)


def _url(cid, sid=None):
    return f"/api/consultations/{cid}/soap" + (f"/{sid}" if sid else "")


# ---------- diff ----------

def test_diff_por_palavra_nas_secoes_de_texto():
    diff = calcular_diff(VERSAO_IA, _editado(plano="Hidratação oral e retorno em 24 horas."))

    assert diff["alterado"] is True
    assert diff["secoes_alteradas"] == ["plano"]
    # mesmo formato que o SoapDiff.test.tsx da extensao usa
    assert _secao(diff, "plano")["trechos"] == [
        {"op": "igual", "texto": "Hidratação oral e retorno em "},
        {"op": "removido", "texto": "48"},
        {"op": "adicionado", "texto": "24"},
        {"op": "igual", "texto": " horas."},
    ]
    assert _secao(diff, "subjetivo") == {
        "secao": "subjetivo", "titulo": "Subjetivo", "tipo": "texto", "alterada": False,
        "trechos": [{"op": "igual", "texto": "Febre há três dias, dor no corpo."}],
    }


def test_diff_por_item_nas_listas():
    diff = calcular_diff(VERSAO_IA, _editado(pendencias=["Hemograma", "Sorologia"]))

    assert _secao(diff, "pendencias")["trechos"] == [
        {"op": "igual", "texto": "Hemograma"},
        {"op": "adicionado", "texto": "Sorologia"},
    ]
    assert _secao(diff, "alertas") == {"secao": "alertas", "titulo": "Alertas", "tipo": "lista",
                                       "alterada": False, "trechos": []}


def test_hipotese_comparada_por_descricao_cid_e_confianca():
    """Trocar so a confianca (ou o CID) tambem conta como alteracao."""
    diff = calcular_diff(VERSAO_IA, _editado(hipoteses=[
        {"descricao": "Dengue", "cid10": "A90", "confianca": "media"},
        {"descricao": "Chikungunya", "cid10": None, "confianca": "baixa"},
    ]))

    assert _secao(diff, "hipoteses")["trechos"] == [
        {"op": "removido", "texto": "Dengue (A90) · confiança alta"},
        {"op": "adicionado", "texto": "Dengue (A90) · confiança media"},
        {"op": "adicionado", "texto": "Chikungunya · confiança baixa"},
    ]


def test_diff_remonta_os_dois_textos_sem_perda():
    antes = "Paciente  refere dor\nlombar há 2 dias."
    depois = "Paciente refere dor lombar intensa há 3 dias."
    trechos = _secao(calcular_diff({"subjetivo": antes}, {"subjetivo": depois}), "subjetivo")["trechos"]

    assert "".join(t["texto"] for t in trechos if t["op"] != "adicionado") == antes
    assert "".join(t["texto"] for t in trechos if t["op"] != "removido") == depois


def test_sem_versao_do_medico_nao_ha_diff():
    assert calcular_diff(VERSAO_IA, None) is None


def test_edicao_igual_a_ia_nao_e_alteracao():
    diff = calcular_diff(VERSAO_IA, dict(VERSAO_IA))
    assert diff["alterado"] is False and diff["secoes_alteradas"] == []


# ---------- repositorio do B39 com o diff ----------

def test_documento_traz_o_diff_e_mantem_a_versao_ia(soap):
    cid, sid = soap
    repo = DocumentoSoapRepository(sessao.obter_sessao())
    assert repo.obter(sid)["diff"] is None

    editado = repo.salvar_edicao(sid, _editado(plano="Retorno amanhã."))

    assert editado["diff"]["secoes_alteradas"] == ["plano"]
    assert editado["versao_ia"]["plano"] == VERSAO_IA["plano"]
    sessao.encerrar_sessao()
    assert DocumentoSoapRepository(sessao.obter_sessao()).mais_recente(cid)["diff"]["alterado"] is True


def test_nova_geracao_vira_o_soap_mais_recente(soap):
    cid, sid = soap
    repo = DocumentoSoapRepository(sessao.obter_sessao())
    repo.salvar_edicao(sid, _editado(plano="Editado."))
    novo = repo.criar(cid, _editado(plano="Gerado de novo."))
    # criado_em igual no mesmo instante em SQLite: garante a ordem
    s = sessao.obter_sessao()
    antigo = s.get(DocumentoSoap, uuid.UUID(sid))
    antigo.criado_em = antigo.criado_em.replace(year=antigo.criado_em.year - 1)
    s.commit()

    atual = repo.mais_recente(cid)
    assert atual["id"] == novo["id"]
    assert atual["versao_medico"] is None and atual["diff"] is None


def test_mais_recente_sem_soap_ou_id_invalido(consulta):
    repo = DocumentoSoapRepository(sessao.obter_sessao())
    assert repo.mais_recente(consulta) is None
    assert repo.mais_recente("nao-e-uuid") is None


# ---------- rotas ----------

def test_criterio_de_aceite_diff_visivel_apos_edicao(client, medico, soap):
    cid, sid = soap
    antes = client.get(_url(cid), headers=medico).get_json()["soap"]
    assert antes["id"] == sid and antes["status"] == "gerado" and antes["diff"] is None

    resp = client.put(_url(cid, sid), headers=medico, json={"versao_medico": _editado(
        plano="Hidratação oral e retorno em 24 horas.", alertas=["Sinais de alarme"])})
    assert resp.status_code == 200
    assert resp.get_json()["soap"]["status"] == "editado"

    depois = client.get(_url(cid), headers=medico).get_json()["soap"]
    assert depois["diff"]["secoes_alteradas"] == ["plano", "alertas"]
    assert {"op": "adicionado", "texto": "24"} in _secao(depois["diff"], "plano")["trechos"]
    assert depois["versao_ia"]["plano"] == VERSAO_IA["plano"]
    assert depois["atual"]["plano"] == "Hidratação oral e retorno em 24 horas."


def test_get_sem_soap_404(client, medico, consulta):
    assert client.get(_url(consulta), headers=medico).status_code == 404


def test_put_soap_inexistente_404(client, medico, consulta):
    resp = client.put(_url(consulta, "00000000-0000-4000-8000-0000000000ff"), headers=medico,
                      json={"versao_medico": VERSAO_IA})
    assert resp.status_code == 404


def test_put_soap_de_outra_consulta_404(client, medico, soap, consulta):
    cid, sid = soap
    outra = ConsultaRepository(sessao.obter_sessao()).criar(
        ConsultaRepository(sessao.obter_sessao()).paciente_da_consulta(cid), "Outra consulta")
    resp = client.put(_url(outra, sid), headers=medico, json={"versao_medico": VERSAO_IA})
    assert resp.status_code == 404


@pytest.mark.parametrize("corpo", [None, {}, {"versao_medico": "texto"}])
def test_put_sem_versao_valida_400(client, medico, soap, corpo):
    cid, sid = soap
    resp = client.put(_url(cid, sid), headers=medico, json=corpo) if corpo is not None else \
        client.put(_url(cid, sid), headers=medico, data="nao json", content_type="text/plain")
    assert resp.status_code == 400


def test_put_fora_do_soapv1_400_com_erros_por_campo(client, medico, soap):
    cid, sid = soap
    resp = client.put(_url(cid, sid), headers=medico, json={"versao_medico": _editado(
        plano="", hipoteses=[{"descricao": "Dengue", "confianca": "90%"}])})

    assert resp.status_code == 400
    erros = resp.get_json()["errors"]
    assert any(e.startswith("plano") for e in erros)
    assert any(e.startswith("hipoteses.0.confianca") for e in erros)


def test_put_em_soap_aprovado_409(client, medico, soap):
    cid, sid = soap
    DocumentoSoapRepository(sessao.obter_sessao()).aprovar(sid)
    resp = client.put(_url(cid, sid), headers=medico, json={"versao_medico": VERSAO_IA})
    assert resp.status_code == 409


def test_rotas_exigem_token_401(client, soap):
    cid, sid = soap
    assert client.get(_url(cid)).status_code == 401
    assert client.put(_url(cid, sid), json={"versao_medico": VERSAO_IA}).status_code == 401


def test_outro_medico_nao_le_nem_edita_403(client, soap, monkeypatch):
    cid, sid = soap
    outro = _login(monkeypatch, user_id=DOCTOR_B)
    assert client.get(_url(cid), headers=outro).status_code == 403
    assert client.put(_url(cid, sid), headers=outro, json={"versao_medico": VERSAO_IA}).status_code == 403


def test_consulta_inexistente_404(client, medico):
    assert client.get(_url("00000000-0000-4000-8000-0000000000ff"), headers=medico).status_code == 404


def test_script_de_exemplo_cria_versao_ia(client, medico, consulta, capsys):
    script = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "criar_soap_exemplo.py"))
    assert script["main"]([consulta]) == 0
    assert "status gerado" in capsys.readouterr().out
    soap = client.get(_url(consulta), headers=medico).get_json()["soap"]
    assert soap["versao_ia"]["hipoteses"][0]["cid10"] == "A90"
    assert soap["prompt"] == {"id": "exemplo-dev", "versao": "0"}
    assert script["main"](["00000000-0000-4000-8000-0000000000ff"]) == 1
