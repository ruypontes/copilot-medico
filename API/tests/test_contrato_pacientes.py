"""B16 - Testes de contrato das rotas de pacientes, consultas, chat, PDF,
extensao, audio e recomendacoes.

Para cada rota: sucesso, erro de validacao, 401/403 e isolamento por medico
(um medico nao acessa paciente de outro).
"""
import io
import importlib

import pytest

from backend import auth_decorators
from ids import DOCTOR_A, DOCTOR_B
from repositories import ConsultaRepository, PacienteRepository, sessao


def _fake_login_as(monkeypatch, profile="medico", user_id=DOCTOR_A):
    """Finge um usuario logado com o perfil e o ID pedidos (sem token real)."""

    def fake_get_user_from_token(token):
        if token != "valid-token":
            raise auth_decorators.AuthError("Token invalido", 401)
        user = {
            "id": user_id,
            "email": "user@example.com",
            "name": "Usuario Teste",
            "profiles": [profile],
            "active": True,
        }
        return user, {"profile": profile}

    monkeypatch.setattr(auth_decorators, "get_user_from_token", fake_get_user_from_token)
    return {"Authorization": "Bearer valid-token"}


@pytest.fixture()
def medico(monkeypatch):
    """Cabecalhos de um medico (doctor-a) logado."""
    return _fake_login_as(monkeypatch, profile="medico", user_id=DOCTOR_A)


@pytest.fixture()
def paciente(client):
    """Paciente do doctor-a com uma consulta. Depende de 'client' para o banco temporario."""
    pid = PacienteRepository(sessao.obter_sessao()).criar(nome="Paciente Teste", medico_id=DOCTOR_A)["id"]
    cid = ConsultaRepository(sessao.obter_sessao()).criar(pid, "Consulta Teste")
    return pid, cid


@pytest.fixture()
def outro_medico(monkeypatch):
    """Cabecalhos de um medico diferente (doctor-b), sem acesso ao paciente do doctor-a."""
    return _fake_login_as(monkeypatch, profile="medico", user_id=DOCTOR_B)


def _perfil_errado(monkeypatch):
    return _fake_login_as(monkeypatch, profile="recepcao", user_id="user-x")


# ---------- GET /api/patient-exists/<id> ----------

def test_patient_exists_success(client, medico, paciente):
    resp = client.get(f"/api/patient-exists/{paciente[0]}", headers=medico)
    assert resp.status_code == 200
    assert resp.get_json()["exists"] is True


def test_patient_exists_unknown_id_returns_false(client, medico):
    resp = client.get("/api/patient-exists/nao-existe", headers=medico)
    assert resp.status_code == 200
    assert resp.get_json()["exists"] is False


def test_patient_exists_requires_token_401(client):
    assert client.get("/api/patient-exists/x").status_code == 401


def test_patient_exists_wrong_profile_403(client, monkeypatch):
    assert client.get("/api/patient-exists/x", headers=_perfil_errado(monkeypatch)).status_code == 403


def test_patient_exists_other_doctor_403(client, outro_medico, paciente):
    assert client.get(f"/api/patient-exists/{paciente[0]}", headers=outro_medico).status_code == 403


# ---------- POST /api/patients ----------

def test_create_patient_success(client, medico):
    resp = client.post("/api/patients", json={"name": "Ana"}, headers=medico)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["patient_name"] == "Ana"
    assert body["doctor_id"] == DOCTOR_A


def test_create_patient_invalid_body_400(client, medico):
    resp = client.post("/api/patients", json=["nao", "e", "objeto"], headers=medico)
    assert resp.status_code == 400


def test_create_patient_requires_token_401(client):
    assert client.post("/api/patients", json={"name": "Ana"}).status_code == 401


def test_create_patient_wrong_profile_403(client, monkeypatch):
    resp = client.post("/api/patients", json={"name": "Ana"}, headers=_perfil_errado(monkeypatch))
    assert resp.status_code == 403


# ---------- GET /api/all-patients ----------

def test_all_patients_lists_only_own_patients(client, outro_medico, paciente):
    # doctor-b lista os pacientes dele: o paciente do doctor-a nao pode aparecer
    resp = client.get("/api/all-patients", headers=outro_medico)
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.get_json()["patients"]]
    assert paciente[0] not in ids


def test_all_patients_success_for_owner(client, medico, paciente):
    resp = client.get("/api/all-patients", headers=medico)
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.get_json()["patients"]]
    assert paciente[0] in ids


def test_all_patients_requires_token_401(client):
    assert client.get("/api/all-patients").status_code == 401


def test_all_patients_wrong_profile_403(client, monkeypatch):
    assert client.get("/api/all-patients", headers=_perfil_errado(monkeypatch)).status_code == 403


# ---------- GET/POST /api/patients/<id>/consultations ----------

def test_list_consultations_success(client, medico, paciente):
    resp = client.get(f"/api/patients/{paciente[0]}/consultations", headers=medico)
    assert resp.status_code == 200
    assert len(resp.get_json()["consultations"]) >= 1


def test_create_consultation_success(client, medico, paciente):
    resp = client.post(
        f"/api/patients/{paciente[0]}/consultations", json={"title": "Retorno"}, headers=medico
    )
    assert resp.status_code == 201
    assert resp.get_json()["consultation_title"] == "Retorno"


def test_consultations_unknown_patient_404(client, medico):
    assert client.get("/api/patients/nao-existe/consultations", headers=medico).status_code == 404


def test_consultations_invalid_body_400(client, medico, paciente):
    resp = client.post(
        f"/api/patients/{paciente[0]}/consultations", json=["x"], headers=medico
    )
    assert resp.status_code == 400


def test_consultations_requires_token_401(client):
    assert client.get("/api/patients/x/consultations").status_code == 401


def test_consultations_wrong_profile_403(client, monkeypatch):
    resp = client.get("/api/patients/x/consultations", headers=_perfil_errado(monkeypatch))
    assert resp.status_code == 403


def test_consultations_other_doctor_403(client, outro_medico, paciente):
    resp = client.get(f"/api/patients/{paciente[0]}/consultations", headers=outro_medico)
    assert resp.status_code == 403


# ---------- GET /api/patients/<id>/consultations/<id>/history ----------

def test_history_success(client, medico, paciente):
    pid, cid = paciente
    resp = client.get(f"/api/patients/{pid}/consultations/{cid}/history", headers=medico)
    assert resp.status_code == 200
    assert "history" in resp.get_json()


def test_history_unknown_consultation_404(client, medico, paciente):
    resp = client.get(f"/api/patients/{paciente[0]}/consultations/nao-existe/history", headers=medico)
    assert resp.status_code == 404


def test_history_requires_token_401(client):
    assert client.get("/api/patients/x/consultations/y/history").status_code == 401


def test_history_wrong_profile_403(client, monkeypatch):
    resp = client.get("/api/patients/x/consultations/y/history", headers=_perfil_errado(monkeypatch))
    assert resp.status_code == 403


def test_history_other_doctor_403(client, outro_medico, paciente):
    pid, cid = paciente
    assert client.get(f"/api/patients/{pid}/consultations/{cid}/history", headers=outro_medico).status_code == 403


# ---------- GET /api/patients/<id>/transcription-log ----------

def test_transcription_log_success(client, medico, paciente):
    resp = client.get(f"/api/patients/{paciente[0]}/transcription-log", headers=medico)
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 0


def test_transcription_log_unknown_patient_404(client, medico):
    assert client.get("/api/patients/nao-existe/transcription-log", headers=medico).status_code == 404


def test_transcription_log_requires_token_401(client):
    assert client.get("/api/patients/x/transcription-log").status_code == 401


def test_transcription_log_wrong_profile_403(client, monkeypatch):
    resp = client.get("/api/patients/x/transcription-log", headers=_perfil_errado(monkeypatch))
    assert resp.status_code == 403


def test_transcription_log_other_doctor_403(client, outro_medico, paciente):
    assert client.get(f"/api/patients/{paciente[0]}/transcription-log", headers=outro_medico).status_code == 403


# ---------- GET /api/patients/<id>/extension-data ----------

def test_extension_data_get_success(client, medico, paciente):
    resp = client.get(f"/api/patients/{paciente[0]}/extension-data", headers=medico)
    assert resp.status_code == 200
    assert resp.get_json()["extension_data"] == []


def test_extension_data_get_unknown_patient_404(client, medico):
    assert client.get("/api/patients/nao-existe/extension-data", headers=medico).status_code == 404


def test_extension_data_get_requires_token_401(client):
    assert client.get("/api/patients/x/extension-data").status_code == 401


def test_extension_data_get_wrong_profile_403(client, monkeypatch):
    resp = client.get("/api/patients/x/extension-data", headers=_perfil_errado(monkeypatch))
    assert resp.status_code == 403


def test_extension_data_get_other_doctor_403(client, outro_medico, paciente):
    assert client.get(f"/api/patients/{paciente[0]}/extension-data", headers=outro_medico).status_code == 403


# ---------- POST /api/extension/extracted-data e alias /api/extracted-data ----------

@pytest.mark.parametrize("rota", ["/api/extension/extracted-data", "/api/extracted-data"])
def test_extracted_data_success(client, medico, paciente, rota):
    resp = client.post(rota, json={
        "patient_id": paciente[0],
        "consultation_id": paciente[1],
        "extracted_content": [{"role": "Anamnese", "text": "Dor de cabeca ha 3 dias"}],
    }, headers=medico)
    assert resp.status_code == 200
    assert resp.get_json()["extension_data"]


@pytest.mark.parametrize("rota", ["/api/extension/extracted-data", "/api/extracted-data"])
def test_extracted_data_validation_400(client, medico, rota):
    resp = client.post(rota, json={"extracted_content": "texto"}, headers=medico)
    assert resp.status_code == 400


@pytest.mark.parametrize("rota", ["/api/extension/extracted-data", "/api/extracted-data"])
def test_extracted_data_requires_token_401(client, rota):
    assert client.post(rota, json={}).status_code == 401


@pytest.mark.parametrize("rota", ["/api/extension/extracted-data", "/api/extracted-data"])
def test_extracted_data_wrong_profile_403(client, monkeypatch, rota):
    resp = client.post(rota, json={}, headers=_perfil_errado(monkeypatch))
    assert resp.status_code == 403


@pytest.mark.parametrize("rota", ["/api/extension/extracted-data", "/api/extracted-data"])
def test_extracted_data_other_doctor_403(client, outro_medico, paciente, rota):
    resp = client.post(rota, json={
        "patient_id": paciente[0], "consultation_id": paciente[1], "extracted_content": "texto",
    }, headers=outro_medico)
    assert resp.status_code == 403


# ---------- POST /api/chat ----------

def test_chat_success(client, medico, paciente):
    pid, cid = paciente
    resp = client.post("/api/chat", json={
        "message": "Ola", "patient_id": pid, "consultation_id": cid,
    }, headers=medico)
    assert resp.status_code == 200
    assert resp.get_json()["ai_response"]


def test_chat_validation_400(client, medico):
    assert client.post("/api/chat", json={}, headers=medico).status_code == 400


def test_chat_requires_token_401(client):
    assert client.post("/api/chat", json={"message": "Ola"}).status_code == 401


def test_chat_wrong_profile_403(client, monkeypatch):
    resp = client.post("/api/chat", json={"message": "Ola"}, headers=_perfil_errado(monkeypatch))
    assert resp.status_code == 403


def test_chat_other_doctor_403(client, outro_medico, paciente):
    resp = client.post("/api/chat", json={
        "message": "Ola", "patient_id": paciente[0],
    }, headers=outro_medico)
    assert resp.status_code == 403


# ---------- POST /api/upload-pdf ----------

def _pdf(texto="Texto do exame"):
    return (io.BytesIO(texto.encode("utf-8")), "exame.pdf")


def test_upload_pdf_success(client, medico, paciente):
    pid, cid = paciente
    resp = client.post("/api/upload-pdf", data={
        "pdf": _pdf(), "patient_id": pid, "consultation_id": cid,
    }, content_type="multipart/form-data", headers=medico)
    assert resp.status_code == 200
    assert resp.get_json()["ai_response"]


def test_upload_pdf_without_file_400(client, medico):
    resp = client.post("/api/upload-pdf", data={}, content_type="multipart/form-data", headers=medico)
    assert resp.status_code == 400


def test_upload_pdf_empty_text_400(client, medico, paciente):
    resp = client.post("/api/upload-pdf", data={
        "pdf": _pdf(" "), "patient_id": paciente[0],
    }, content_type="multipart/form-data", headers=medico)
    assert resp.status_code == 400


def test_upload_pdf_requires_token_401(client):
    resp = client.post("/api/upload-pdf", data={"pdf": _pdf()}, content_type="multipart/form-data")
    assert resp.status_code == 401


def test_upload_pdf_wrong_profile_403(client, monkeypatch):
    resp = client.post("/api/upload-pdf", data={"pdf": _pdf()},
                       content_type="multipart/form-data", headers=_perfil_errado(monkeypatch))
    assert resp.status_code == 403


def test_upload_pdf_other_doctor_403(client, outro_medico, paciente):
    resp = client.post("/api/upload-pdf", data={
        "pdf": _pdf(), "patient_id": paciente[0],
    }, content_type="multipart/form-data", headers=outro_medico)
    assert resp.status_code == 403


# ---------- POST /api/recommendations ----------

def test_recommendations_success(client, medico, paciente, monkeypatch):
    # B38: as sugestoes saem das transcricoes da janela, nao do chat inteiro.
    import server
    from repositories import TranscricaoRepository

    pid, cid = paciente
    TranscricaoRepository(sessao.obter_sessao()).adicionar(pid, cid, texto="Paciente com tosse", duracao_s=60)
    monkeypatch.setattr(server.chat_ia, "gerar_resposta_unica",
                        lambda _i, _c: '{"itens": [{"tipo": "exame", "texto": "Auscultar pulmões"}]}')
    resp = client.post("/api/recommendations", json={
        "patient_id": pid, "consultation_id": cid,
    }, headers=medico)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["itens"] == [{"tipo": "exame", "texto": "Auscultar pulmões"}]
    assert body["recommendation"]


def test_recommendations_validation_400(client, medico):
    assert client.post("/api/recommendations", json={"patient_id": "x"}, headers=medico).status_code == 400


def test_recommendations_requires_token_401(client):
    assert client.post("/api/recommendations", json={}).status_code == 401


def test_recommendations_wrong_profile_403(client, monkeypatch):
    resp = client.post("/api/recommendations", json={}, headers=_perfil_errado(monkeypatch))
    assert resp.status_code == 403


def test_recommendations_other_doctor_403(client, outro_medico, paciente):
    pid, cid = paciente
    resp = client.post("/api/recommendations", json={
        "patient_id": pid, "consultation_id": cid,
    }, headers=outro_medico)
    assert resp.status_code == 403


# ---------- POST /api/transcribe_audio ----------

class _FakeAudioProcessor:
    def processar_audio(self, caminho):
        return {
            "full_text": "Paciente relata dor de cabeca",
            "dialogue": [{"speaker": "medico", "text": "Bom dia", "start": 0, "end": 2}],
        }


def _audio(nome="audio.wav"):
    return (io.BytesIO(b"RIFF....fake"), nome)


def test_transcribe_audio_success(client, medico, paciente, monkeypatch):
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "audio_processor", _FakeAudioProcessor())
    pid, cid = paciente
    resp = client.post("/api/transcribe_audio", data={
        "audio_file": _audio(), "patient_id": pid, "consultation_id": cid,
    }, content_type="multipart/form-data", headers=medico)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["is_error"] is False
    assert body["transcription"]


class _FakeGemini:
    nome = "gemini"

    def __init__(self, resultado=None, erro=None):
        self.resultado = resultado
        self.erro = erro

    def processar_audio(self, caminho):
        if self.erro:
            raise self.erro
        return self.resultado


_TURNOS_GEMINI = [
    {"role": "Médico", "role_key": "doctor", "text": "Bom dia", "speaker_id": 0, "start": 0.0, "end": 2.0},
    {"role": "Paciente", "role_key": "patient", "text": "Estou com febre", "speaker_id": 1,
     "start": 2.0, "end": 65.0},
]


def test_transcribe_audio_usa_o_provedor_padrao(client, medico, paciente, monkeypatch):
    """B31: com o provedor configurado, a rota grava os turnos marcados por ele."""
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "audio_processor", _FakeAudioProcessor())
    monkeypatch.setattr(server, "transcription_provider", _FakeGemini({
        "full_text": "Médico: Bom dia\nPaciente: Estou com febre",
        "dialogue": _TURNOS_GEMINI, "speakers_count": 2, "duration": 65.0,
    }))
    pid, cid = paciente
    resp = client.post("/api/transcribe_audio", data={
        "audio_file": _audio(), "patient_id": pid, "consultation_id": cid,
    }, content_type="multipart/form-data", headers=medico)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["is_error"] is False
    assert body["transcription"] == "Médico: Bom dia\nPaciente: Estou com febre"
    assert [t["role_key"] for t in body["log_entry"]["dialogue"]] == ["doctor", "patient"]
    assert body["log_entry"]["duration"] == "1:05"


def test_transcribe_audio_provedor_falha_cai_no_diarizador(client, medico, paciente, monkeypatch):
    """B31: erro do Gemini (cota, rede) nao derruba a rota; o Diarizador assume."""
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "audio_processor", _FakeAudioProcessor())
    monkeypatch.setattr(server, "transcription_provider", _FakeGemini(erro=RuntimeError("429")))
    pid, cid = paciente
    resp = client.post("/api/transcribe_audio", data={
        "audio_file": _audio(), "patient_id": pid, "consultation_id": cid,
    }, content_type="multipart/form-data", headers=medico)
    assert resp.status_code == 200
    assert resp.get_json()["transcription"] == "Paciente relata dor de cabeca"


def test_transcribe_audio_sem_fala_nao_grava(client, medico, paciente, monkeypatch):
    server = importlib.import_module("server")
    monkeypatch.setattr(server, "transcription_provider", _FakeGemini({
        "full_text": "", "dialogue": [], "speakers_count": 0, "duration": 0.0,
    }))
    pid, cid = paciente
    resp = client.post("/api/transcribe_audio", data={
        "audio_file": _audio(), "patient_id": pid, "consultation_id": cid,
    }, content_type="multipart/form-data", headers=medico)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["is_error"] is True
    assert "log_entry" not in body


def test_transcribe_audio_usa_provedor_do_env(client, medico, paciente, monkeypatch):
    """B32: com TRANSCRIPTION_PROVIDER definido, a rota usa o provedor no lugar do Diarizador."""
    server = importlib.import_module("server")

    class _FakeWhisper:
        nome = "whisper"

        def processar_audio(self, caminho):
            return {
                "full_text": "Falante não identificado: Bom dia",
                "dialogue": [{"role": "Falante não identificado", "role_key": "unknown",
                              "text": "Bom dia", "speaker_id": None, "start": 0.0, "end": 65.0}],
                "speakers_count": 1,
                "duration": 65.0,
            }

    monkeypatch.setattr(server, "audio_processor", _FakeAudioProcessor())
    monkeypatch.setattr(server, "transcription_provider", _FakeWhisper())
    pid, cid = paciente
    resp = client.post("/api/transcribe_audio", data={
        "audio_file": _audio(), "patient_id": pid, "consultation_id": cid,
    }, content_type="multipart/form-data", headers=medico)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["transcription"] == "Falante não identificado: Bom dia"
    assert body["log_entry"]["dialogue"][0]["role_key"] == "unknown"
    assert body["log_entry"]["duration"] == "1:05"


def test_transcribe_audio_without_file_400(client, medico):
    resp = client.post("/api/transcribe_audio", data={"patient_id": "x"},
                       content_type="multipart/form-data", headers=medico)
    assert resp.status_code == 400


def test_transcribe_audio_without_patient_id_400(client, medico):
    resp = client.post("/api/transcribe_audio", data={"audio_file": _audio()},
                       content_type="multipart/form-data", headers=medico)
    assert resp.status_code == 400


def test_transcribe_audio_unknown_patient_404(client, medico):
    resp = client.post("/api/transcribe_audio", data={
        "audio_file": _audio(), "patient_id": "nao-existe",
    }, content_type="multipart/form-data", headers=medico)
    assert resp.status_code == 404


def test_transcribe_audio_requires_token_401(client):
    resp = client.post("/api/transcribe_audio", data={"audio_file": _audio()},
                       content_type="multipart/form-data")
    assert resp.status_code == 401


def test_transcribe_audio_wrong_profile_403(client, monkeypatch):
    resp = client.post("/api/transcribe_audio", data={"audio_file": _audio()},
                       content_type="multipart/form-data", headers=_perfil_errado(monkeypatch))
    assert resp.status_code == 403


def test_transcribe_audio_other_doctor_403(client, outro_medico, paciente):
    resp = client.post("/api/transcribe_audio", data={
        "audio_file": _audio(), "patient_id": paciente[0],
    }, content_type="multipart/form-data", headers=outro_medico)
    assert resp.status_code == 403
