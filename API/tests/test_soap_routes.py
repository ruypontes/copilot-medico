from backend import soap_service
from repositories import ConsultaRepository, MensagemRepository, PacienteRepository, sessao


SOAP_GERADO = {
    "subjetivo": "Paciente relata cefaleia.",
    "objetivo": "Sem sinais vitais informados.",
    "avaliacao": "Cefaleia.",
    "plano": "Investigar evolução.",
    "hipoteses": [{"descricao": "Cefaleia", "cid10": "R51", "confianca": "media"}],
    "alertas": [],
    "pendencias": ["Aferir pressão arterial"],
}


def test_fluxo_soap_gerar_editar_e_aprovar(auth_client, monkeypatch):
    paciente = PacienteRepository(sessao.obter_sessao()).criar(nome="Paciente SOAP")
    consulta_id = ConsultaRepository(sessao.obter_sessao()).criar(paciente["id"], "Consulta SOAP")
    MensagemRepository(sessao.obter_sessao()).adicionar(
        consulta_id, "user", "Paciente relata cefaleia há dois dias. CPF 529.982.247-25."
    )
    contexto_enviado = []

    def gerar_soap_falso(contexto):
        contexto_enviado.append(contexto)
        return SOAP_GERADO

    monkeypatch.setattr(soap_service, "gerar_soap", gerar_soap_falso)

    response = auth_client.post(f"/api/consultations/{consulta_id}/soap")
    assert response.status_code == 201
    assert "529.982.247-25" not in contexto_enviado[0]
    assert "[CPF_1]" in contexto_enviado[0]
    soap = response.get_json()["soap"]
    document_id = soap["id"]
    assert soap["versao_ia"] == SOAP_GERADO
    assert soap["status"] == "gerado"

    versao_medico = {**SOAP_GERADO, "plano": "Solicitar retorno em sete dias."}
    response = auth_client.put(
        f"/api/consultations/{consulta_id}/soap/{document_id}",
        json={"versao_medico": versao_medico},
    )
    assert response.status_code == 200
    assert response.get_json()["soap"]["versao_medico"] == versao_medico
    assert response.get_json()["soap"]["status"] == "editado"

    response = auth_client.post(
        f"/api/consultations/{consulta_id}/soap/{document_id}/approve"
    )
    assert response.status_code == 200
    assert response.get_json()["soap"]["status"] == "aprovado"

    response = auth_client.get(f"/api/consultations/{consulta_id}/soap")
    assert response.status_code == 200
    soap_salvo = response.get_json()["soap"]
    assert soap_salvo["versao_medico"]["plano"] == versao_medico["plano"]
    assert soap_salvo["status"] == "aprovado"

    response = auth_client.put(
        f"/api/consultations/{consulta_id}/soap/{document_id}",
        json={"versao_medico": versao_medico},
    )
    assert response.status_code == 404


def test_gerar_soap_exige_conteudo_na_consulta(auth_client):
    paciente = PacienteRepository(sessao.obter_sessao()).criar(nome="Paciente Vazio")
    consulta_id = ConsultaRepository(sessao.obter_sessao()).criar(paciente["id"], "Consulta Vazia")

    response = auth_client.post(f"/api/consultations/{consulta_id}/soap")

    assert response.status_code == 400