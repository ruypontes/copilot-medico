import io

from repositories import (
    ConsultaRepository,
    DadoExtensaoRepository,
    MensagemRepository,
    PacienteRepository,
    TranscricaoRepository,
    sessao,
)


def _repo(cls):
    return cls(sessao.obter_sessao())


def _novo_paciente(nome="Teste"):
    return _repo(PacienteRepository).criar(nome=nome)["id"]


def _nova_consulta(paciente_id, titulo):
    return _repo(ConsultaRepository).criar(paciente_id, titulo)


# Fixtures usadas aqui (ver conftest.py):
#   client       -> anonimo, para os testes que exigem 401/403
#   auth_client  -> autenticado como administrador
#   auth_headers -> fabrica de headers por perfil
#
# O helper local _auth_headers(monkeypatch, profile=...) foi removido: ele
# era replicado em cada teste e nao cobria as rotas que faltavam token,
# origem dos 16 erros 401 da D-17.


def test_patient_exists_endpoint_false(auth_client):
    resp = auth_client.get('/api/patient-exists/does-not-exist')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["exists"] is False


def test_create_patient_endpoint(auth_client):
    resp = auth_client.post('/api/patients', json={"name": "Ana"})
    assert resp.status_code == 201
    payload = resp.get_json()
    assert payload["status"] == "success"
    assert payload["patient_id"]
    assert payload["patient_name"] == "Ana"
    assert payload["first_consultation_id"]


def test_chat_endpoint_creates_patient_and_consultation(auth_client):
    resp = auth_client.post('/api/chat', json={"message": "Olá doutor"})
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["status"] == "success"
    assert "ai_response" in payload
    assert payload["consultation_id"]
    # When chat creates new patient, response includes patient_id
    assert payload.get("patient_id")


def test_chat_endpoint_with_existing_patient_and_consultation(auth_client):
    # Prepare a patient and consultation
    pid = _novo_paciente("Teste")
    cid = _nova_consulta(pid, "Consulta X")
    resp = auth_client.post('/api/chat', json={"message": "Pergunta", "patient_id": pid, "consultation_id": cid})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["consultation_id"] == cid


def test_upload_pdf_endpoint_happy_path(auth_client):
    # Create simple in-memory file pretending to be a PDF; stub will read its bytes as text
    data = {
        'pdf': (io.BytesIO(b"exaMENe do paciente Joao"), 'doc.pdf')
    }
    resp = auth_client.post('/api/upload-pdf', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["status"] == "success"
    assert payload["ai_response"].startswith("[stubbed AI reply]")
    assert payload["consultation_id"]


def test_extension_extracted_data_requires_token(client):
    resp = client.post('/api/extension/extracted-data', json={})
    assert resp.status_code == 401
    assert resp.get_json()["status"] == "error"


def test_extension_extracted_data_rejects_unauthorized_profile(client, auth_headers):
    pid = _novo_paciente("Teste")
    cid = _nova_consulta(pid, "Consulta X")

    resp = client.post(
        '/api/extension/extracted-data',
        json={
            "patient_id": pid,
            "consultation_id": cid,
            "extracted_content": [{"role": "peso", "text": "70"}],
        },
        headers=auth_headers("recepcao"),
    )

    assert resp.status_code == 403
    assert resp.get_json()["status"] == "error"


def test_extension_extracted_data_rejects_invalid_payload(client, auth_headers):
    resp = client.post(
        '/api/extension/extracted-data',
        json={
            "patient_id": "paciente_123",
            "consultation_id": "consulta_456",
            "extracted_content": [{"role": "peso"}],
        },
        headers=auth_headers("administrador"),
    )

    assert resp.status_code == 400
    assert resp.get_json()["status"] == "error"


def test_extension_extracted_data_saves_user_and_ai_messages(client, auth_headers):
    pid = _novo_paciente("Teste")
    cid = _nova_consulta(pid, "Consulta X")

    resp = client.post(
        '/api/extension/extracted-data',
        json={
            "patient_id": pid,
            "consultation_id": cid,
            "source_url": "https://sistema-prontuario.com/atendimento",
            "extracted_content": [
                {"role": "peso", "text": "70"},
                {"role": "altura", "text": "1.75"},
                {"role": "Anamnese", "text": "Paciente relata dor de cabeca"},
            ],
        },
        headers=auth_headers("administrador"),
    )

    payload = resp.get_json()
    assert resp.status_code == 200
    assert payload["status"] == "success"
    assert payload["patient_id"] == pid
    assert payload["consultation_id"] == cid
    assert payload["ai_response"].startswith("[stubbed AI reply]")

    history = _repo(MensagemRepository).historico(cid)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    saved_text = history[0]["parts"][0]["text"]
    assert "Dados capturados da extensao Chrome" in saved_text
    assert "Fonte: https://sistema-prontuario.com/atendimento" in saved_text
    assert "peso: 70" in saved_text
    assert "altura: 1.75" in saved_text
    assert "Anamnese: Paciente relata dor de cabeca" in saved_text
    assert history[1]["role"] == "model"
    assert history[1]["parts"][0]["text"] == payload["ai_response"]

    extension_items = _repo(DadoExtensaoRepository).listar(pid)
    assert len(extension_items) == 1
    assert extension_items[0]["patient_id"] == pid
    assert extension_items[0]["consultation_id"] == cid
    assert extension_items[0]["source"] == "extension"
    assert extension_items[0]["type"] == "extracted_data"


def test_extension_extracted_data_accepts_camel_case_without_consultation(client, auth_headers):
    pid = _novo_paciente("Teste")

    resp = client.post(
        '/api/extension/extracted-data',
        json={
            "patientId": pid,
            "sourceUrl": "https://sistema-prontuario.com/atendimento",
            "createdAt": "2026-07-07T12:00:00",
            "extractedData": {
                "peso": "70",
                "queixa": ["dor", "febre"],
            },
        },
        headers=auth_headers("administrador"),
    )

    payload = resp.get_json()
    assert resp.status_code == 200
    assert payload["status"] == "success"
    assert payload["patient_id"] == pid
    assert payload["consultation_id"] is None
    assert payload["ai_response"] is None
    assert payload["extension_data"]["source"] == "extension"
    # Datas saem sempre em UTC com fuso (B20); sem fuso, o cliente e lido como UTC.
    assert payload["extension_data"]["created_at"] == "2026-07-07T12:00:00+00:00"
    assert payload["extension_data"]["content"]["peso"] == "70"


def test_extension_extracted_data_rejects_consultation_from_other_patient(client, auth_headers):
    pid = _novo_paciente("Teste")
    other_pid = _novo_paciente("Outro")
    other_cid = _nova_consulta(other_pid, "Consulta X")

    resp = client.post(
        '/api/extension/extracted-data',
        json={
            "patient_id": pid,
            "consultation_id": other_cid,
            "extracted_content": [{"role": "peso", "text": "70"}],
        },
        headers=auth_headers("administrador"),
    )

    assert resp.status_code == 404
    assert resp.get_json()["status"] == "error"


def test_legacy_extracted_data_alias_saves_structured_data(client, auth_headers):
    pid = _novo_paciente("Teste")

    resp = client.post(
        '/api/extracted-data',
        json={
            "patient_id": pid,
            "extracted_data": {"pressao": "120/80"},
        },
        headers=auth_headers("administrador"),
    )

    payload = resp.get_json()
    assert resp.status_code == 200
    assert payload["status"] == "success"
    assert payload["extension_data"]["content"]["pressao"] == "120/80"


def test_get_patient_extension_data_returns_extension_items_and_transcriptions(auth_client):
    pid = _novo_paciente("Teste")
    saved = _repo(DadoExtensaoRepository).adicionar(pid, [{"role": "peso", "text": "70"}])
    transcription = _repo(TranscricaoRepository).adicionar(
        pid, None, texto="transcricao", duracao_s=10
    )

    resp = auth_client.get(f'/api/patients/{pid}/extension-data')

    payload = resp.get_json()
    assert resp.status_code == 200
    assert payload["status"] == "success"
    assert payload["patient_id"] == pid
    assert payload["extension_data"][0]["id"] == saved["id"]
    assert payload["transcriptions"][0]["id"] == transcription["id"]
    assert payload["transcriptions"][0]["source"] == "extension"


def test_transcribe_audio_rejects_consultation_from_other_patient(auth_client):
    pid = _novo_paciente("Teste")
    other_pid = _novo_paciente("Outro")
    other_cid = _nova_consulta(other_pid, "Consulta X")

    resp = auth_client.post(
        '/api/transcribe_audio',
        data={
            "patient_id": pid,
            "consultation_id": other_cid,
            "duration": "1",
            "audio_file": (io.BytesIO(b"not-a-real-wav"), "recording.wav"),
        },
        content_type='multipart/form-data',
    )

    assert resp.status_code == 404
    assert resp.get_json()["status"] == "error"


def test_create_and_list_consultations(auth_client):
    # First create a patient
    r = auth_client.post('/api/patients', json={"name": "Carlos"})
    pid = r.get_json()["patient_id"]
    # Create a new consultation with imports param (no errors)
    resp = auth_client.post(f'/api/patients/{pid}/consultations', json={"title": "Nova Consulta", "import_consultation_ids": []})
    assert resp.status_code == 201
    new_id = resp.get_json()["consultation_id"]
    # List consultations
    list_resp = auth_client.get(f'/api/patients/{pid}/consultations')
    assert list_resp.status_code == 200
    consultations = list_resp.get_json()["consultations"]
    assert any(c["id"] == new_id for c in consultations)


def test_get_consultation_history(auth_client):
    r = auth_client.post('/api/patients', json={"name": "Paula"})
    pid = r.get_json()["patient_id"]
    cid = r.get_json()["first_consultation_id"]
    # Add a message into that consultation
    _repo(MensagemRepository).adicionar(cid, "user", "Oi")
    resp = auth_client.get(f"/api/patients/{pid}/consultations/{cid}/history")
    assert resp.status_code == 200
    history = resp.get_json()["history"]
    assert len(history) >= 1


essential_keys = {"status", "patients"}

def test_get_all_patients(auth_client):
    # Ensure at least one patient exists
    auth_client.post('/api/patients', json={"name": "ListMe"})
    resp = auth_client.get('/api/all-patients')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert set(payload.keys()) >= essential_keys
    assert isinstance(payload["patients"], list)


def test_import_history_ignores_consultation_from_other_patient(auth_client):
    # B20: o historico passou a ser buscado pelo id da consulta; a rota tem
    # que conferir a posse para nao copiar o chat de outro paciente.
    pid = _novo_paciente("Teste")
    other_pid = _novo_paciente("Outro")
    other_cid = _nova_consulta(other_pid, "Consulta X")
    _repo(MensagemRepository).adicionar(other_cid, "user", "segredo do outro paciente")

    resp = auth_client.post(
        f'/api/patients/{pid}/consultations',
        json={"title": "Nova", "import_consultation_ids": [other_cid]},
    )

    assert resp.status_code == 201
    history = _repo(MensagemRepository).historico(resp.get_json()["consultation_id"])
    assert all("segredo" not in m["parts"][0]["text"] for m in history)


def test_create_patient_with_unknown_doctor_returns_400(auth_client):
    resp = auth_client.post('/api/patients', json={
        "name": "Ana", "doctor_id": "00000000-0000-4000-8000-0000000000ff",
    })

    assert resp.status_code == 400
    assert resp.get_json()["status"] == "error"
