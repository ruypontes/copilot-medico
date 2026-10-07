"""Nenhuma PII pode sair pelas rotas (B25+B26 / US016-CA001, CA003).

Este e o teste que a CA003 pede: intercepta o provedor de IA e inspeciona o
payload que REALMENTE sairia da maquina. Os testes de unidade provam que o
anonimizador funciona; este prova que ele esta ligado no caminho certo - a
falha classica e ter o anonimizador pronto e esquecer de chama-lo em uma das
tres rotas.
"""
from __future__ import annotations

import io
import json
import re

import pytest


# PII plantada nas requisicoes. Nenhuma pode aparecer no que vai ao provedor.
NOME = "Maria Souza"
CPF = "529.982.247-25"
TELEFONE = "(81) 99876-5432"
EMAIL = "maria.souza@clinica.com.br"
NASCIMENTO = "12/03/1980"
CEP = "50670-901"

SENSIVEIS = [NOME, CPF, TELEFONE, EMAIL, NASCIMENTO, CEP]

# Padroes genericos: pegam PII que nao plantamos, mas que vazou mesmo assim.
PADROES_PROIBIDOS = {
    "CPF": re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}"),
    "e-mail": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "CEP": re.compile(r"\b\d{5}-\d{3}\b"),
    "data completa": re.compile(r"\b\d{2}/\d{2}/\d{4}\b"),
}


@pytest.fixture()
def payloads_capturados(monkeypatch):
    """Substitui o provedor e guarda tudo que lhe seria enviado."""
    import server

    enviados: list[str] = []

    def falso_send_message(patient_id, consultation_id, message_text):
        enviados.append(message_text)
        # Devolve tokens para exercitar a reidratacao na volta.
        return "Analise de [PACIENTE_1]: confira o CPF [CPF_1]."

    monkeypatch.setattr(server.gemini_connection, "send_message", falso_send_message)
    return enviados


@pytest.fixture()
def paciente(auth_client):
    resposta = auth_client.post("/api/patients", json={"name": NOME})
    assert resposta.status_code == 201
    return resposta.get_json()


def _conferir_sem_pii(payload: str) -> None:
    for valor in SENSIVEIS:
        assert valor not in payload, f"{valor!r} vazou para o provedor"
    for rotulo, padrao in PADROES_PROIBIDOS.items():
        achado = padrao.search(payload)
        assert achado is None, f"padrao de {rotulo} vazou: {achado.group(0)!r}"


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------

def test_chat_nao_envia_pii_ao_provedor(auth_client, paciente, payloads_capturados):
    texto = (
        f"{NOME}, CPF {CPF}, nascida em {NASCIMENTO}, telefone {TELEFONE}, "
        f"e-mail {EMAIL}, CEP {CEP}. Queixa de cefaleia ha 3 dias."
    )

    resposta = auth_client.post("/api/chat", json={
        "message": texto,
        "patient_id": paciente["patient_id"],
        "consultation_id": paciente["first_consultation_id"],
    })

    assert resposta.status_code == 200
    assert len(payloads_capturados) == 1
    _conferir_sem_pii(payloads_capturados[0])
    # O conteudo clinico precisa sobreviver, senao a anonimizacao inutiliza
    # a consulta.
    assert "cefaleia" in payloads_capturados[0]


def test_chat_reidrata_a_resposta_para_o_medico(auth_client, paciente, payloads_capturados):
    """US016-CA002: o medico ve os valores reais, o provedor nao."""
    resposta = auth_client.post("/api/chat", json={
        "message": f"{NOME} informou o CPF {CPF}.",
        "patient_id": paciente["patient_id"],
        "consultation_id": paciente["first_consultation_id"],
    })

    exibido = resposta.get_json()["ai_response"]

    assert CPF in exibido, "resposta deveria voltar reidratada na exibicao"
    assert "[CPF_1]" not in exibido


def test_historico_guarda_tokens_e_nao_pii(auth_client, paciente, payloads_capturados):
    """A coluna chama-se `conteudo_pseudonimizado`; precisa honrar o nome."""
    consulta = paciente["first_consultation_id"]
    auth_client.post("/api/chat", json={
        "message": f"CPF {CPF} confirmado.",
        "patient_id": paciente["patient_id"],
        "consultation_id": consulta,
    })

    historico = auth_client.get(
        f"/api/patients/{paciente['patient_id']}/consultations/{consulta}/history"
    ).get_json()["history"]

    guardado = " ".join(
        parte.get("text", "")
        for item in historico
        for parte in item.get("parts", [])
    )

    assert CPF not in guardado, "PII foi persistida no historico"
    assert "[CPF_1]" in guardado


# ---------------------------------------------------------------------------
# POST /api/upload-pdf
# ---------------------------------------------------------------------------

def test_upload_pdf_nao_envia_pii_ao_provedor(auth_client, paciente, payloads_capturados):
    conteudo = f"Laudo de {NOME}, CPF {CPF}, nascido em {NASCIMENTO}. Hemoglobina 13.5."

    resposta = auth_client.post(
        "/api/upload-pdf",
        data={
            "pdf": (io.BytesIO(conteudo.encode("utf-8")), "laudo.pdf"),
            "patient_id": paciente["patient_id"],
            "consultation_id": paciente["first_consultation_id"],
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 200
    assert len(payloads_capturados) == 1
    _conferir_sem_pii(payloads_capturados[0])
    assert "Hemoglobina" in payloads_capturados[0]


# ---------------------------------------------------------------------------
# POST /api/extension/extracted-data
# ---------------------------------------------------------------------------

def test_dados_da_extensao_nao_enviam_pii_ao_provedor(
    auth_client, paciente, payloads_capturados
):
    resposta = auth_client.post("/api/extension/extracted-data", json={
        "patient_id": paciente["patient_id"],
        "consultation_id": paciente["first_consultation_id"],
        "source_url": "https://prontuario.example.com/atendimento",
        "extracted_content": [
            {"role": "nome", "text": NOME},
            {"role": "cpf", "text": CPF},
            {"role": "nascimento", "text": NASCIMENTO},
            {"role": "queixa", "text": "dor toracica ha 2 horas"},
        ],
    })

    assert resposta.status_code == 200
    assert len(payloads_capturados) == 1
    _conferir_sem_pii(payloads_capturados[0])
    assert "dor toracica" in payloads_capturados[0]


# ---------------------------------------------------------------------------
# Estabilidade dos tokens entre requisicoes (B25)
# ---------------------------------------------------------------------------

def test_tokens_sao_estaveis_entre_mensagens_da_consulta(
    auth_client, paciente, payloads_capturados
):
    """Mesmo CPF em duas requisicoes deve render o mesmo token.

    So funciona porque o mapa e persistido cifrado entre as chamadas (B26);
    sem isso cada requisicao recomecaria do [CPF_1] para valores diferentes.
    """
    comum = {
        "patient_id": paciente["patient_id"],
        "consultation_id": paciente["first_consultation_id"],
    }
    auth_client.post("/api/chat", json={"message": f"CPF {CPF}.", **comum})
    auth_client.post("/api/chat", json={"message": f"Confirmar CPF {CPF}.", **comum})

    assert len(payloads_capturados) == 2
    token_primeiro = re.search(r"\[CPF_\d+\]", payloads_capturados[0]).group(0)
    token_segundo = re.search(r"\[CPF_\d+\]", payloads_capturados[1]).group(0)

    assert token_primeiro == token_segundo


# ---------------------------------------------------------------------------
# Ciclo de vida do cofre
# ---------------------------------------------------------------------------

def test_logout_descarta_a_chave_da_sessao(auth_client):
    from backend.anonimizacao import cofres, cripto

    cofres.guardar("test-valid-token", cripto.criar_cofre("qualquer")[0])

    resposta = auth_client.post("/api/auth/logout")

    assert resposta.status_code == 200
    assert cofres.obter("test-valid-token") is None


# ---------------------------------------------------------------------------
# B69: a ESTRUTURA persistida tambem nao pode conter PII
# ---------------------------------------------------------------------------

def test_conteudo_da_extensao_e_persistido_anonimizado(
    auth_client, paciente, payloads_capturados
):
    """O B25/B26 anonimizava so o texto enviado ao LLM; a estrutura crua ia
    para `dado_extensao.conteudo` com nome e CPF em claro. Esta e a lacuna
    que o B69 fecha - e a razao de o merge ter mantido a ideia dele."""
    auth_client.post("/api/extension/extracted-data", json={
        "patient_id": paciente["patient_id"],
        "consultation_id": paciente["first_consultation_id"],
        "extracted_content": [
            {"role": "nome", "text": NOME},
            {"role": "cpf", "text": CPF},
            {"role": "telefone", "text": TELEFONE},
            {"role": "queixa", "text": "dor toracica ha 2 horas"},
        ],
    })

    guardado = auth_client.get(
        f"/api/patients/{paciente['patient_id']}/extension-data"
    ).get_json()

    bruto = json.dumps(guardado, ensure_ascii=False)

    for valor in [NOME, CPF, TELEFONE]:
        assert valor not in bruto, f"{valor!r} foi persistido em claro"
    for rotulo, padrao in PADROES_PROIBIDOS.items():
        achado = padrao.search(bruto)
        assert achado is None, f"padrao de {rotulo} persistido: {achado.group(0)!r}"

    # Os rotulos de campo e o conteudo clinico sobrevivem.
    assert "queixa" in bruto
    assert "dor toracica" in bruto


def test_token_persistido_e_o_mesmo_enviado_ao_provedor(
    auth_client, paciente, payloads_capturados
):
    """Estrutura e mensagem compartilham o mapa da consulta: o CPF tem de
    receber o MESMO token nos dois caminhos, senao a reidratacao de um
    corromperia o outro."""
    auth_client.post("/api/extension/extracted-data", json={
        "patient_id": paciente["patient_id"],
        "consultation_id": paciente["first_consultation_id"],
        "extracted_content": [{"role": "cpf", "text": CPF}],
    })

    persistido = json.dumps(auth_client.get(
        f"/api/patients/{paciente['patient_id']}/extension-data"
    ).get_json())

    token_no_payload = re.search(r"\[CPF_\d+\]", payloads_capturados[0]).group(0)

    assert token_no_payload in persistido
