"""B52/B53 - botao flutuante e "Inserir no prontuario" (US019).

B52: o botao flutuante envia as notas lidas pelo adaptador do PEP para
pep-import; o e-SUS PEC le as quatro secoes do SOAP nativo dele.
B53: o SOAP so pode ser marcado como inserido no PEP depois de aprovado, e so
uma vez (criterio de aceite: clique insere; status inserido_no_pep).
"""
import pytest

from backend import auth_decorators, pep_import
from ids import DOCTOR_A, DOCTOR_B
from repositories import (
    ConsultaRepository,
    DocumentoSoapRepository,
    PacienteRepository,
    TransicaoInvalida,
    sessao,
)

SOAP = {
    "subjetivo": "Tosse seca há três dias.",
    "objetivo": "Ausculta sem ruídos.",
    "avaliacao": "Infecção de vias aéreas superiores.",
    "plano": "Hidratação e retorno se febre.",
    "hipoteses": [{"descricao": "IVAS", "cid10": "J06.9", "confianca": "alta"}],
    "alertas": [],
    "pendencias": [],
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
    pid = PacienteRepository(sessao.obter_sessao()).criar(nome="Paciente PEP", medico_id=DOCTOR_A)["id"]
    return ConsultaRepository(sessao.obter_sessao()).criar(pid, "Consulta PEP")


@pytest.fixture()
def soap(consulta):
    return consulta, DocumentoSoapRepository(sessao.obter_sessao()).criar(consulta, SOAP)["id"]


def _url(cid, sid, acao):
    return f"/api/consultations/{cid}/soap/{sid}/{acao}"


# ---------- B52: notas do e-SUS PEC no pep-import ----------

def test_pep_import_aceita_o_soap_do_esus_pec():
    out = pep_import.parse_pep_import({"pep_origem": "esus-pec", "campos": {
        "subjetivo": "Tosse.", "objetivo": "Sem febre.", "avaliacao": "IVAS.", "plano": "Retorno."}})
    assert list(out["campos"]) == ["subjetivo", "objetivo", "avaliacao", "plano"]
    assert pep_import.summarize(out)["notas"] == ["subjetivo", "objetivo", "avaliacao", "plano"]
    assert "Subjetivo: Tosse." in pep_import.format_for_prompt(out)


def test_rota_pep_import_registra_o_envio_do_botao_flutuante(client, medico, consulta):
    resp = client.post(f"/api/consultations/{consulta}/pep-import", headers=medico, json={
        "pep_origem": "esus-pec", "source_url": "http://localhost:8081/atendimento",
        "campos": {"subjetivo": "Tosse seca.", "plano": "Retorno em 7 dias."}})
    assert resp.status_code == 200
    assert resp.get_json()["resumo"]["notas"] == ["subjetivo", "plano"]


# ---------- B53: repositorio ----------

def test_so_insere_depois_de_aprovar(soap):
    _cid, sid = soap
    repo = DocumentoSoapRepository(sessao.obter_sessao())
    with pytest.raises(TransicaoInvalida, match="Aprove"):
        repo.marcar_inserido_no_pep(sid)

    repo.aprovar(sid)
    assert repo.marcar_inserido_no_pep(sid)["status"] == "inserido_no_pep"

    with pytest.raises(TransicaoInvalida, match="ja inserido"):
        repo.marcar_inserido_no_pep(sid)


def test_editado_tambem_precisa_aprovar(soap):
    _cid, sid = soap
    repo = DocumentoSoapRepository(sessao.obter_sessao())
    repo.salvar_edicao(sid, {**SOAP, "plano": "Retorno amanhã."})
    with pytest.raises(TransicaoInvalida):
        repo.marcar_inserido_no_pep(sid)


def test_soap_inexistente(temp_db_file):
    assert DocumentoSoapRepository(sessao.obter_sessao()).marcar_inserido_no_pep("nao-e-uuid") is None


# ---------- B53: rotas ----------

def test_criterio_de_aceite_aprovar_e_inserir(client, medico, soap):
    cid, sid = soap
    # antes de aprovar: a insercao e recusada
    assert client.post(_url(cid, sid, "inserted"), headers=medico, json={"pep": "esus-pec"}).status_code == 409

    aprovado = client.post(_url(cid, sid, "approve"), headers=medico)
    assert aprovado.status_code == 200
    assert aprovado.get_json()["soap"]["status"] == "aprovado"
    assert aprovado.get_json()["soap"]["approved_at"]

    inserido = client.post(_url(cid, sid, "inserted"), headers=medico, json={"pep": "esus-pec"})
    assert inserido.status_code == 200
    assert inserido.get_json()["soap"]["status"] == "inserido_no_pep"

    # o GET reflete o status; inserir de novo e editar sao recusados
    assert client.get(f"/api/consultations/{cid}/soap", headers=medico).get_json()["soap"]["status"] == "inserido_no_pep"
    assert client.post(_url(cid, sid, "inserted"), headers=medico, json={"pep": "esus-pec"}).status_code == 409
    assert client.put(f"/api/consultations/{cid}/soap/{sid}", headers=medico,
                      json={"versao_medico": SOAP}).status_code == 409
    assert client.post(_url(cid, sid, "approve"), headers=medico).status_code == 409


def test_aprovar_de_novo_nao_muda_nada(client, medico, soap):
    cid, sid = soap
    primeiro = client.post(_url(cid, sid, "approve"), headers=medico).get_json()["soap"]
    segundo = client.post(_url(cid, sid, "approve"), headers=medico).get_json()["soap"]
    assert segundo["approved_at"] == primeiro["approved_at"]


@pytest.mark.parametrize("corpo", [None, {}, {"pep": "prontuario-x"}, {"pep": 1}])
def test_inserted_exige_pep_conhecido_400(client, medico, soap, corpo):
    cid, sid = soap
    client.post(_url(cid, sid, "approve"), headers=medico)
    resp = client.post(_url(cid, sid, "inserted"), headers=medico, json=corpo) if corpo is not None else \
        client.post(_url(cid, sid, "inserted"), headers=medico, data="x", content_type="text/plain")
    assert resp.status_code == 400


@pytest.mark.parametrize("acao", ["approve", "inserted"])
def test_soap_de_outra_consulta_ou_inexistente_404(client, medico, soap, acao):
    cid, sid = soap
    outra = ConsultaRepository(sessao.obter_sessao()).criar(
        ConsultaRepository(sessao.obter_sessao()).paciente_da_consulta(cid), "Outra")
    assert client.post(_url(outra, sid, acao), headers=medico, json={"pep": "esus-pec"}).status_code == 404
    assert client.post(_url(cid, "00000000-0000-4000-8000-0000000000ff", acao), headers=medico,
                       json={"pep": "esus-pec"}).status_code == 404


@pytest.mark.parametrize("acao", ["approve", "inserted"])
def test_exige_token_e_dono_da_consulta(client, soap, monkeypatch, acao):
    cid, sid = soap
    assert client.post(_url(cid, sid, acao), json={"pep": "esus-pec"}).status_code == 401
    outro = _login(monkeypatch, user_id=DOCTOR_B)
    assert client.post(_url(cid, sid, acao), headers=outro, json={"pep": "esus-pec"}).status_code == 403
