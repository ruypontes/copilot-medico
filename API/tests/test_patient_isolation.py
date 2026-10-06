from io import BytesIO

from ids import DOCTOR_A, DOCTOR_B

def _auth_headers(monkeypatch, user_id, profile="medico"):
    from backend import auth_decorators

    def fake_get_user_from_token(token):
        if token != "valid-token":
            raise auth_decorators.AuthError("Token invalido", 401)

        return (
            {
                "id": user_id,
                "email": f"{user_id}@example.com",
                "name": f"Doctor {user_id}",
                "profiles": [profile],
                "active": True,
            },
            {"profile": profile},
        )

    monkeypatch.setattr(
        auth_decorators,
        "get_user_from_token",
        fake_get_user_from_token,
    )

    return {"Authorization": "Bearer valid-token"}


def test_doctor_patient_isolation(client, monkeypatch):
    """
    Testa isolamento entre dois médicos:

    Médico A -> Paciente A = permitido
    Médico A -> Paciente B = proibido

    Médico B -> Paciente B = permitido
    Médico B -> Paciente A = proibido
    """

    # ============================================================
    # 1. Médico A cria o próprio paciente
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente A"},
        headers=headers_a,
    )

    assert response.status_code == 201, response.get_json()

    patient_a = response.get_json()
    patient_a_id = patient_a["patient_id"]

    assert patient_a["doctor_id"] == DOCTOR_A

    # ============================================================
    # 2. Médico B cria o próprio paciente
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente B"},
        headers=headers_b,
    )

    assert response.status_code == 201, response.get_json()

    patient_b = response.get_json()
    patient_b_id = patient_b["patient_id"]

    assert patient_b["doctor_id"] == DOCTOR_B

    # ============================================================
    # 3. Médico A pode acessar o próprio paciente
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.get(
        f"/api/patient-exists/{patient_a_id}",
        headers=headers_a,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()
    assert data["exists"] is True

    # ============================================================
    # 4. Médico A NÃO pode acessar paciente do Médico B
    # ============================================================

    response = client.get(
        f"/api/patient-exists/{patient_b_id}",
        headers=headers_a,
    )

    assert response.status_code == 403, response.get_json()

    # ============================================================
    # 5. Médico B pode acessar o próprio paciente
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.get(
        f"/api/patient-exists/{patient_b_id}",
        headers=headers_b,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()
    assert data["exists"] is True

    # ============================================================
    # 6. Médico B NÃO pode acessar paciente do Médico A
    # ============================================================

    response = client.get(
        f"/api/patient-exists/{patient_a_id}",
        headers=headers_b,
    )

    assert response.status_code == 403, response.get_json()


def test_doctor_cannot_spoof_patient_owner(client, monkeypatch):
    """
    Garante que um médico não consegue criar um paciente
    pertencente a outro médico simplesmente enviando doctor_id
    no JSON.
    """

    # ============================================================
    # 1. Médico A tenta criar paciente dizendo que pertence
    #    ao Médico B
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/patients",
        json={
            "name": "Paciente Spoof",
            "doctor_id": DOCTOR_B,
        },
        headers=headers_a,
    )

    assert response.status_code == 201, response.get_json()

    patient = response.get_json()

    # O servidor deve IGNORAR doctor_id=DOCTOR_B
    # e utilizar o médico autenticado.
    assert patient["doctor_id"] == DOCTOR_A

    patient_id = patient["patient_id"]

    # ============================================================
    # 2. Médico B tenta acessar o paciente
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.get(
        f"/api/patient-exists/{patient_id}",
        headers=headers_b,
    )

    assert response.status_code == 403, response.get_json()

    # ============================================================
    # 3. Médico A continua podendo acessar o paciente
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.get(
        f"/api/patient-exists/{patient_id}",
        headers=headers_a,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()
    assert data["exists"] is True
def test_doctor_all_patients_isolation(client, monkeypatch):
    """
    Verifica que /api/all-patients retorna somente os pacientes
    pertencentes ao médico autenticado.
    """

    # ============================================================
    # 1. Médico A cria Paciente A
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente A"},
        headers=headers_a,
    )

    assert response.status_code == 201, response.get_json()

    patient_a_id = response.get_json()["patient_id"]

    # ============================================================
    # 2. Médico B cria Paciente B
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente B"},
        headers=headers_b,
    )

    assert response.status_code == 201, response.get_json()

    patient_b_id = response.get_json()["patient_id"]

    # ============================================================
    # 3. Médico A lista pacientes
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.get(
        "/api/all-patients",
        headers=headers_a,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()

    # A resposta normalmente possui a lista em "patients".
    patients = data.get("patients", data)

    # Se a resposta for um dicionário inesperado, falhamos
    # mostrando o conteúdo para facilitar o diagnóstico.
    assert isinstance(patients, list), data

    patient_ids = [patient["id"] for patient in patients]

    assert patient_a_id in patient_ids
    assert patient_b_id not in patient_ids

    # ============================================================
    # 4. Médico B lista pacientes
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.get(
        "/api/all-patients",
        headers=headers_b,
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()
    patients = data.get("patients", data)

    assert isinstance(patients, list), data

    patient_ids = [patient["id"] for patient in patients]

    assert patient_b_id in patient_ids
    assert patient_a_id not in patient_ids


def test_doctor_transcription_log_isolation(client, monkeypatch):
    """
    Verifica que o log de transcrição de um paciente
    não pode ser acessado por outro médico.
    """

    # ============================================================
    # 1. Médico A cria Paciente A
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente A"},
        headers=headers_a,
    )

    assert response.status_code == 201, response.get_json()

    patient_a_id = response.get_json()["patient_id"]

    # ============================================================
    # 2. Médico B cria Paciente B
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente B"},
        headers=headers_b,
    )

    assert response.status_code == 201, response.get_json()

    patient_b_id = response.get_json()["patient_id"]

    # ============================================================
    # 3. Médico A acessa o próprio log
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.get(
        f"/api/patients/{patient_a_id}/transcription-log",
        headers=headers_a,
    )

    assert response.status_code == 200, response.get_json()

    # ============================================================
    # 4. Médico A tenta acessar o log de B
    # ============================================================

    response = client.get(
        f"/api/patients/{patient_b_id}/transcription-log",
        headers=headers_a,
    )

    assert response.status_code == 403, response.get_json()

    # ============================================================
    # 5. Médico B acessa o próprio log
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.get(
        f"/api/patients/{patient_b_id}/transcription-log",
        headers=headers_b,
    )

    assert response.status_code == 200, response.get_json()

    # ============================================================
    # 6. Médico B tenta acessar o log de A
    # ============================================================

    response = client.get(
        f"/api/patients/{patient_a_id}/transcription-log",
        headers=headers_b,
    )

    assert response.status_code == 403, response.get_json()


def test_doctor_extension_data_isolation(client, monkeypatch):
    """
    Verifica que os dados de extensão de um paciente
    não podem ser acessados por outro médico.
    """

    # ============================================================
    # 1. Médico A cria Paciente A
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente A"},
        headers=headers_a,
    )

    assert response.status_code == 201, response.get_json()

    patient_a_id = response.get_json()["patient_id"]

    # ============================================================
    # 2. Médico B cria Paciente B
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente B"},
        headers=headers_b,
    )

    assert response.status_code == 201, response.get_json()

    patient_b_id = response.get_json()["patient_id"]

    # ============================================================
    # 3. Médico A acessa os próprios dados
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.get(
        f"/api/patients/{patient_a_id}/extension-data",
        headers=headers_a,
    )

    assert response.status_code == 200, response.get_json()

    # ============================================================
    # 4. Médico A tenta acessar dados de B
    # ============================================================

    response = client.get(
        f"/api/patients/{patient_b_id}/extension-data",
        headers=headers_a,
    )

    assert response.status_code == 403, response.get_json()

    # ============================================================
    # 5. Médico B acessa os próprios dados
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.get(
        f"/api/patients/{patient_b_id}/extension-data",
        headers=headers_b,
    )

    assert response.status_code == 200, response.get_json()

    # ============================================================
    # 6. Médico B tenta acessar dados de A
    # ============================================================

    response = client.get(
        f"/api/patients/{patient_a_id}/extension-data",
        headers=headers_b,
    )

    assert response.status_code == 403, response.get_json()
def test_doctor_consultations_isolation(client, monkeypatch):
    """
    Verifica o isolamento das consultas entre médicos.

    Médico A -> Paciente A -> permitido
    Médico A -> Paciente B -> proibido

    Médico B -> Paciente B -> permitido
    Médico B -> Paciente A -> proibido
    """

    # ============================================================
    # 1. Médico A cria Paciente A
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente A"},
        headers=headers_a,
    )

    assert response.status_code == 201, response.get_json()

    patient_a = response.get_json()
    patient_a_id = patient_a["patient_id"]

    # A criação do paciente já cria uma primeira consulta.
    consultation_a_id = patient_a["first_consultation_id"]

    assert consultation_a_id

    # ============================================================
    # 2. Médico B cria Paciente B
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente B"},
        headers=headers_b,
    )

    assert response.status_code == 201, response.get_json()

    patient_b = response.get_json()
    patient_b_id = patient_b["patient_id"]

    consultation_b_id = patient_b["first_consultation_id"]

    assert consultation_b_id

    # ============================================================
    # 3. Médico A pode listar as consultas do próprio paciente
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.get(
        f"/api/patients/{patient_a_id}/consultations",
        headers=headers_a,
    )

    assert response.status_code == 200, response.get_json()

    # ============================================================
    # 4. Médico A NÃO pode acessar consultas do paciente B
    # ============================================================

    response = client.get(
        f"/api/patients/{patient_b_id}/consultations",
        headers=headers_a,
    )

    assert response.status_code == 403, response.get_json()

    # ============================================================
    # 5. Médico B pode listar as consultas do próprio paciente
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.get(
        f"/api/patients/{patient_b_id}/consultations",
        headers=headers_b,
    )

    assert response.status_code == 200, response.get_json()

    # ============================================================
    # 6. Médico B NÃO pode acessar consultas do paciente A
    # ============================================================

    response = client.get(
        f"/api/patients/{patient_a_id}/consultations",
        headers=headers_b,
    )

    assert response.status_code == 403, response.get_json()


def test_doctor_consultation_history_isolation(client, monkeypatch):
    """
    Verifica o isolamento do histórico de uma consulta.

    O médico só pode acessar o histórico de consultas
    pertencentes aos seus próprios pacientes.
    """

    # ============================================================
    # 1. Médico A cria Paciente A
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente A"},
        headers=headers_a,
    )

    assert response.status_code == 201, response.get_json()

    patient_a = response.get_json()
    patient_a_id = patient_a["patient_id"]
    consultation_a_id = patient_a["first_consultation_id"]

    # ============================================================
    # 2. Médico B cria Paciente B
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente B"},
        headers=headers_b,
    )

    assert response.status_code == 201, response.get_json()

    patient_b = response.get_json()
    patient_b_id = patient_b["patient_id"]
    consultation_b_id = patient_b["first_consultation_id"]

    # ============================================================
    # 3. Médico A acessa o próprio histórico
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.get(
        f"/api/patients/{patient_a_id}/consultations/{consultation_a_id}/history",
        headers=headers_a,
    )

    assert response.status_code == 200, response.get_json()

    # ============================================================
    # 4. Médico A tenta acessar histórico de B
    # ============================================================

    response = client.get(
        f"/api/patients/{patient_b_id}/consultations/{consultation_b_id}/history",
        headers=headers_a,
    )

    assert response.status_code == 403, response.get_json()

    # ============================================================
    # 5. Médico B acessa o próprio histórico
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.get(
        f"/api/patients/{patient_b_id}/consultations/{consultation_b_id}/history",
        headers=headers_b,
    )

    assert response.status_code == 200, response.get_json()

    # ============================================================
    # 6. Médico B tenta acessar histórico de A
    # ============================================================

    response = client.get(
        f"/api/patients/{patient_a_id}/consultations/{consultation_a_id}/history",
        headers=headers_b,
    )

    assert response.status_code == 403, response.get_json()

def test_doctor_chat_isolation(client, monkeypatch):
    """
    Verifica que um médico só pode utilizar o chat
    associado aos seus próprios pacientes.
    """

    # ============================================================
    # 1. Médico A cria Paciente A
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente A"},
        headers=headers_a,
    )

    assert response.status_code == 201, response.get_json()

    patient_a = response.get_json()
    patient_a_id = patient_a["patient_id"]
    consultation_a_id = patient_a["first_consultation_id"]

    # ============================================================
    # 2. Médico B cria Paciente B
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente B"},
        headers=headers_b,
    )

    assert response.status_code == 201, response.get_json()

    patient_b = response.get_json()
    patient_b_id = patient_b["patient_id"]
    consultation_b_id = patient_b["first_consultation_id"]

    # ============================================================
    # 3. Médico A utiliza o chat do próprio paciente
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/chat",
        json={
            "patient_id": patient_a_id,
            "consultation_id": consultation_a_id,
            "message": "Mensagem de teste",
        },
        headers=headers_a,
    )

    assert response.status_code == 200, response.get_json()

    # ============================================================
    # 4. Médico A tenta utilizar o chat do paciente B
    # ============================================================

    response = client.post(
        "/api/chat",
        json={
            "patient_id": patient_b_id,
            "consultation_id": consultation_b_id,
            "message": "Tentativa de acesso indevido",
        },
        headers=headers_a,
    )

    assert response.status_code == 403, response.get_json()

    # ============================================================
    # 5. Médico B utiliza o chat do próprio paciente
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/chat",
        json={
            "patient_id": patient_b_id,
            "consultation_id": consultation_b_id,
            "message": "Mensagem de teste do médico B",
        },
        headers=headers_b,
    )

    assert response.status_code == 200, response.get_json()

    # ============================================================
    # 6. Médico B tenta utilizar o chat do paciente A
    # ============================================================

    response = client.post(
        "/api/chat",
        json={
            "patient_id": patient_a_id,
            "consultation_id": consultation_a_id,
            "message": "Tentativa de acesso indevido",
        },
        headers=headers_b,
    )

    assert response.status_code == 403, response.get_json()


def test_doctor_transcription_audio_isolation(client, monkeypatch):
    """
    Verifica que um médico não consegue enviar uma transcrição
    para o paciente pertencente a outro médico.
    """

    # ============================================================
    # 1. Médico A cria Paciente A
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente A"},
        headers=headers_a,
    )

    assert response.status_code == 201, response.get_json()

    patient_a = response.get_json()
    patient_a_id = patient_a["patient_id"]
    consultation_a_id = patient_a["first_consultation_id"]

    # ============================================================
    # 2. Médico B cria Paciente B
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente B"},
        headers=headers_b,
    )

    assert response.status_code == 201, response.get_json()

    patient_b = response.get_json()
    patient_b_id = patient_b["patient_id"]
    consultation_b_id = patient_b["first_consultation_id"]

    # ============================================================
    # 3. Médico A tenta enviar áudio para o próprio paciente
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/transcribe_audio",
        data={
            "patient_id": patient_a_id,
            "consultation_id": consultation_a_id,
            "audio_file": (
                BytesIO(b"audio de teste"),
                "teste.wav",
            ),
        },
        headers=headers_a,
        content_type="multipart/form-data",
    )

    # O importante aqui é que NÃO seja bloqueado por ownership.
    # O processamento do áudio pode produzir outro resultado
    # dependendo da implementação.
    assert response.status_code != 403, response.get_json()

    # ============================================================
    # 4. Médico A tenta enviar áudio para paciente B
    # ============================================================

    response = client.post(
        "/api/transcribe_audio",
        data={
            "patient_id": patient_b_id,
            "consultation_id": consultation_b_id,
            "audio_file": (
                BytesIO(b"audio de teste"),
                "teste.wav",
            ),
        },
        headers=headers_a,
        content_type="multipart/form-data",
    )

    # Aqui o bloqueio de ownership deve acontecer antes
    # do processamento do áudio.
    assert response.status_code == 403, response.get_json()

    # ============================================================
    # 5. Médico B tenta enviar áudio para paciente A
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/transcribe_audio",
        data={
            "patient_id": patient_a_id,
            "consultation_id": consultation_a_id,
            "audio_file": (
                BytesIO(b"audio de teste"),
                "teste.wav",
            ),
        },
        headers=headers_b,
        content_type="multipart/form-data",
    )

    assert response.status_code == 403, response.get_json()
def test_doctor_extracted_data_isolation(client, monkeypatch):
    """
    Verifica que dados extraídos não podem ser gravados
    no paciente pertencente a outro médico.

    Testa as duas rotas:
        /api/extension/extracted-data
        /api/extracted-data
    """

    # ============================================================
    # 1. Médico A cria Paciente A
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente A"},
        headers=headers_a,
    )

    assert response.status_code == 201, response.get_json()

    patient_a = response.get_json()
    patient_a_id = patient_a["patient_id"]
    consultation_a_id = patient_a["first_consultation_id"]

    # ============================================================
    # 2. Médico B cria Paciente B
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/patients",
        json={"name": "Paciente B"},
        headers=headers_b,
    )

    assert response.status_code == 201, response.get_json()

    patient_b = response.get_json()
    patient_b_id = patient_b["patient_id"]
    consultation_b_id = patient_b["first_consultation_id"]

    # ============================================================
    # Dados fictícios para o teste
    # ============================================================

    extracted_data = {
        "patient_id": patient_a_id,
        "consultation_id": consultation_a_id,
        "extracted_content": {
            "pressao": "120/80",
            "temperatura": "36.5",
        },
    }

    # ============================================================
    # 3. Médico A envia dados para o próprio paciente
    #    usando /api/extension/extracted-data
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/extension/extracted-data",
        json=extracted_data,
        headers=headers_a,
    )

    assert response.status_code != 403, response.get_json()

    # ============================================================
    # 4. Médico A tenta enviar dados para Paciente B
    # ============================================================

    response = client.post(
        "/api/extension/extracted-data",
        json={
            "patient_id": patient_b_id,
            "consultation_id": consultation_b_id,
            "extracted_content": {
                "pressao": "999/999",
            },
        },
        headers=headers_a,
    )

    assert response.status_code == 403, response.get_json()

    # ============================================================
    # 5. Médico B envia dados para o próprio paciente
    #    usando /api/extension/extracted-data
    # ============================================================

    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/extension/extracted-data",
        json={
            "patient_id": patient_b_id,
            "consultation_id": consultation_b_id,
            "extracted_content": {
                "pressao": "120/80",
            },
        },
        headers=headers_b,
    )

    assert response.status_code != 403, response.get_json()

    # ============================================================
    # 6. Médico B tenta enviar dados para Paciente A
    # ============================================================

    response = client.post(
        "/api/extension/extracted-data",
        json={
            "patient_id": patient_a_id,
            "consultation_id": consultation_a_id,
            "extracted_content": {
                "pressao": "999/999",
            },
        },
        headers=headers_b,
    )

    assert response.status_code == 403, response.get_json()

    # ============================================================
    # 7. Agora testa a rota /api/extracted-data
    # ============================================================

    headers_a = _auth_headers(monkeypatch, DOCTOR_A)

    response = client.post(
        "/api/extracted-data",
        json={
            "patient_id": patient_b_id,
            "consultation_id": consultation_b_id,
            "extracted_content": {
                "teste": "acesso indevido",
            },
        },
        headers=headers_a,
    )

    assert response.status_code == 403, response.get_json()

    # Médico B deve conseguir acessar o próprio paciente.
    headers_b = _auth_headers(monkeypatch, DOCTOR_B)

    response = client.post(
        "/api/extracted-data",
        json={
            "patient_id": patient_b_id,
            "consultation_id": consultation_b_id,
            "extracted_content": {
                "teste": "acesso permitido",
            },
        },
        headers=headers_b,
    )

    assert response.status_code != 403, response.get_json()