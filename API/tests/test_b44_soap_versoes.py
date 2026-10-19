"""B44 - versoes IA e medico do SOAP com diff (US018).

Criterio de aceite: diff visivel apos edicao. A versao da IA fica intacta, a
edicao do medico vai para `versao_medico` e o GET devolve a diferenca por
secao (palavra nas secoes de texto, item nas listas).
"""
import pytest

from backend import auth_decorators
from backend.soap_diff import SoapInvalido, calcular_diff, validar_versao
from ids import DOCTOR_A, DOCTOR_B
from models import DocumentoSoap, StatusSoap
from repositories import ConsultaRepository, PacienteRepository, SoapNaoEditavel, SoapRepository, sessao

VERSAO_IA = {
    "subjetivo": "Febre há três dias, dor no corpo.",
    "objetivo": "Temperatura 38,9 °C.",
    "avaliacao": "Provável dengue sem sinais de alarme.",
    "plano": "Hidratação oral e retorno em 48 horas.",
    "hipoteses": ["Dengue (A90)"],
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
    """Consulta com um SOAP recem-gerado pela IA."""
    SoapRepository(sessao.obter_sessao()).registrar_versao_ia(consulta, VERSAO_IA)
    return consulta


def _editado(**mudancas):
    return {**VERSAO_IA, **mudancas}


def _secao(diff, nome):
    return next(s for s in diff["secoes"] if s["secao"] == nome)


def _url(cid):
    return f"/api/consultations/{cid}/soap"


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
    diff = calcular_diff(VERSAO_IA, _editado(
        hipoteses=["Chikungunya"], pendencias=["Hemograma", "Sorologia"]))

    assert _secao(diff, "hipoteses")["trechos"] == [
        {"op": "removido", "texto": "Dengue (A90)"},
        {"op": "adicionado", "texto": "Chikungunya"},
    ]
    assert _secao(diff, "pendencias")["trechos"] == [
        {"op": "igual", "texto": "Hemograma"},
        {"op": "adicionado", "texto": "Sorologia"},
    ]
    assert _secao(diff, "alertas") == {"secao": "alertas", "titulo": "Alertas", "tipo": "lista",
                                       "alterada": False, "trechos": []}


def test_diff_remonta_os_dois_textos_sem_perda():
    antes = "Paciente  refere dor\nlombar há 2 dias."
    depois = "Paciente refere dor lombar intensa há 3 dias."
    trechos = _secao(calcular_diff({"subjetivo": antes}, {"subjetivo": depois}), "subjetivo")["trechos"]

    assert "".join(t["texto"] for t in trechos if t["op"] != "adicionado") == antes
    assert "".join(t["texto"] for t in trechos if t["op"] != "removido") == depois


def test_sem_versao_do_medico_nao_ha_diff():
    assert calcular_diff(VERSAO_IA, None) is None


def test_edicao_igual_a_ia_nao_e_alteracao():
    diff = calcular_diff(validar_versao(VERSAO_IA), validar_versao(VERSAO_IA))
    assert diff["alterado"] is False and diff["secoes_alteradas"] == []


# ---------- validacao ----------

def test_validacao_normaliza_e_completa_secoes():
    versao = validar_versao({"plano": "  Retorno.  ", "pendencias": [" Hemograma ", "  "]})
    assert versao["plano"] == "Retorno."
    assert versao["pendencias"] == ["Hemograma"]
    assert versao["subjetivo"] == "" and versao["alertas"] == []


@pytest.mark.parametrize("dados, erro", [
    ("texto", "objeto"),
    ({"diagnostico": "x"}, "desconhecidas"),
    ({"plano": ["lista"]}, "texto"),
    ({"alertas": "um alerta"}, "lista"),
    ({"alertas": [1]}, "lista"),
    ({"plano": "x" * 20_001}, "caracteres"),
    ({"pendencias": ["x"] * 51}, "itens"),
])
def test_validacao_rejeita_formato_invalido(dados, erro):
    with pytest.raises(SoapInvalido, match=erro):
        validar_versao(dados)


# ---------- repositorio ----------

def test_versao_ia_nao_muda_com_a_edicao(soap):
    repo = SoapRepository(sessao.obter_sessao())
    salvo = repo.salvar_versao_medico(soap, _editado(plano="Retorno amanhã."))

    assert salvo["status"] == "editado"
    assert salvo["versao_ia"]["plano"] == VERSAO_IA["plano"]
    assert salvo["versao_medico"]["plano"] == "Retorno amanhã."
    sessao.encerrar_sessao()
    assert SoapRepository(sessao.obter_sessao()).atual(soap)["versao_ia"] == validar_versao(VERSAO_IA)


def test_desfazer_a_edicao_volta_ao_status_gerado(soap):
    repo = SoapRepository(sessao.obter_sessao())
    repo.salvar_versao_medico(soap, _editado(plano="Outro plano."))
    assert repo.salvar_versao_medico(soap, VERSAO_IA)["status"] == "gerado"


def test_soap_aprovado_nao_pode_ser_editado(soap):
    s = sessao.obter_sessao()
    s.query(DocumentoSoap).update({"status": StatusSoap.APROVADO})
    s.commit()
    with pytest.raises(SoapNaoEditavel):
        SoapRepository(s).salvar_versao_medico(soap, _editado(plano="x"))


def test_nova_geracao_vira_o_soap_atual(soap):
    repo = SoapRepository(sessao.obter_sessao())
    repo.salvar_versao_medico(soap, _editado(plano="Editado."))
    repo.registrar_versao_ia(soap, _editado(plano="Gerado de novo."))

    atual = repo.atual(soap)
    assert atual["versao_ia"]["plano"] == "Gerado de novo."
    assert atual["versao_medico"] is None and atual["diff"] is None


def test_consulta_inexistente(temp_db_file):
    repo = SoapRepository(sessao.obter_sessao())
    assert repo.registrar_versao_ia("00000000-0000-4000-8000-0000000000ff", VERSAO_IA) is None
    assert repo.atual("nao-e-uuid") is None
    assert repo.salvar_versao_medico("nao-e-uuid", VERSAO_IA) is None


# ---------- rotas ----------

def test_criterio_de_aceite_diff_visivel_apos_edicao(client, medico, soap):
    antes = client.get(_url(soap), headers=medico).get_json()["soap"]
    assert antes["status"] == "gerado" and antes["diff"] is None

    resp = client.put(_url(soap), headers=medico, json={"versao_medico": _editado(
        plano="Hidratação oral e retorno em 24 horas.", alertas=["Sinais de alarme"])})
    assert resp.status_code == 200
    assert resp.get_json()["soap"]["status"] == "editado"

    depois = client.get(_url(soap), headers=medico).get_json()["soap"]
    assert depois["diff"]["secoes_alteradas"] == ["plano", "alertas"]
    assert {"op": "adicionado", "texto": "24"} in _secao(depois["diff"], "plano")["trechos"]
    assert depois["versao_ia"]["plano"] == VERSAO_IA["plano"]


def test_get_sem_soap_404(client, medico, consulta):
    assert client.get(_url(consulta), headers=medico).status_code == 404


def test_put_sem_soap_404(client, medico, consulta):
    resp = client.put(_url(consulta), headers=medico, json={"versao_medico": VERSAO_IA})
    assert resp.status_code == 404


@pytest.mark.parametrize("corpo", [None, {}, {"versao_medico": "texto"}, {"versao_medico": {"x": "y"}}])
def test_put_invalido_400(client, medico, soap, corpo):
    resp = client.put(_url(soap), headers=medico, json=corpo) if corpo is not None else \
        client.put(_url(soap), headers=medico, data="nao json", content_type="text/plain")
    assert resp.status_code == 400


def test_put_em_soap_aprovado_409(client, medico, soap):
    s = sessao.obter_sessao()
    s.query(DocumentoSoap).update({"status": StatusSoap.INSERIDO_NO_PEP})
    s.commit()
    resp = client.put(_url(soap), headers=medico, json={"versao_medico": VERSAO_IA})
    assert resp.status_code == 409


def test_rotas_exigem_token_401(client, soap):
    assert client.get(_url(soap)).status_code == 401
    assert client.put(_url(soap), json={"versao_medico": VERSAO_IA}).status_code == 401


def test_outro_medico_nao_le_nem_edita_403(client, soap, monkeypatch):
    outro = _login(monkeypatch, user_id=DOCTOR_B)
    assert client.get(_url(soap), headers=outro).status_code == 403
    assert client.put(_url(soap), headers=outro, json={"versao_medico": VERSAO_IA}).status_code == 403


def test_consulta_inexistente_404(client, medico):
    assert client.get(_url("00000000-0000-4000-8000-0000000000ff"), headers=medico).status_code == 404


def test_script_de_exemplo_cria_versao_ia(client, medico, consulta, capsys):
    import runpy
    from pathlib import Path

    script = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "criar_soap_exemplo.py"))
    assert script["main"]([consulta]) == 0
    assert "status gerado" in capsys.readouterr().out
    assert client.get(_url(consulta), headers=medico).get_json()["soap"]["versao_ia"]["hipoteses"]
    assert script["main"](["00000000-0000-4000-8000-0000000000ff"]) == 1
