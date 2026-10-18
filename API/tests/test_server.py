"""
Testes de rota com as dependencias de persistencia mockadas (B15).

Migrado de unittest para pytest. Tres problemas da versao anterior:

1. `from API.server import app` no topo do modulo importava o servidor durante
   a COLETA do pytest, antes de qualquer fixture rodar - ou seja, antes dos
   stubs de vosk/speech_recognition. O app agora chega pela fixture
   `auth_client`, que so e construida depois dos stubs.
2. Os sys.path.insert manuais foram substituidos por `pythonpath = .` no
   pytest.ini.
3. O alvo `patch('patient_db.get_patient_data')` nao existia. Desde o B20
   a persistencia e feita por repositorios: os testes trocam as fabricas
   `server._pacientes` / `server._consultas`, resolvidas em tempo de chamada.
"""
from unittest.mock import patch



# ---------------------------------------------------------------------------
# POST /api/patients
# ---------------------------------------------------------------------------

def test_create_patient_success(auth_client):
    """Criar paciente deve retornar 201 e propagar os IDs gerados."""
    with patch("server._pacientes") as mock_pacientes, \
         patch("server._consultas") as mock_consultas:

        mock_criar = mock_pacientes.return_value.criar
        mock_criar.return_value = {"id": "NEW_TEST_ID_001", "name": "Novo Paciente", "doctor_id": None}
        mock_add = mock_consultas.return_value.criar
        mock_add.return_value = "CONSULTA_ID_001"

        response = auth_client.post("/api/patients", json={"name": "Novo Paciente"})

        assert response.status_code == 201, "Deve retornar 201 ao criar paciente"

        mock_add.assert_called_once_with("NEW_TEST_ID_001", "Primeira Consulta")
        assert mock_criar.call_count == 1
        assert mock_criar.call_args.kwargs["nome"] == "Novo Paciente"

        body = response.get_json()
        assert body["patient_id"] == "NEW_TEST_ID_001"
        assert body["first_consultation_id"] == "CONSULTA_ID_001"


def test_create_patient_requires_authentication(client):
    """Sem token, a rota protegida responde 401 (e nao 201)."""
    response = client.post("/api/patients", json={"name": "Sem Token"})

    assert response.status_code == 401
    assert response.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /api/patient-exists/<id>
# ---------------------------------------------------------------------------

def test_check_patient_exists_found(auth_client):
    with patch("server._pacientes") as mock_pacientes:
        mock_get = mock_pacientes.return_value.obter
        mock_get.return_value = {"name": "Existente"}

        response = auth_client.get("/api/patient-exists/existing_id")

        assert response.status_code == 200
        assert response.get_json()["exists"] is True
        mock_get.assert_called_once_with("existing_id")


def test_check_patient_exists_not_found(auth_client):
    with patch("server._pacientes") as mock_pacientes:
        mock_pacientes.return_value.obter.return_value = None
        response = auth_client.get("/api/patient-exists/non_existing_id")

        assert response.status_code == 200
        assert response.get_json()["exists"] is False


# ---------------------------------------------------------------------------
# GET /api/all-patients
# ---------------------------------------------------------------------------

def test_get_all_patients_success(auth_client):
    mock_data = [
        {"id": "id_pac_1", "name": "Paciente A"},
        {"id": "id_pac_2", "name": "Paciente B"},
    ]
    with patch("server._pacientes") as mock_pacientes:
        mock_all = mock_pacientes.return_value.listar
        mock_all.return_value = mock_data
        response = auth_client.get("/api/all-patients")

        assert response.status_code == 200, "Deve retornar 200 OK."
        mock_all.assert_called_once()

        body = response.get_json()
        assert body["status"] == "success"
        assert body["patients"] == mock_data


def test_get_all_patients_empty(auth_client):
    with patch("server._pacientes") as mock_pacientes:
        mock_pacientes.return_value.listar.return_value = []
        response = auth_client.get("/api/all-patients")

        assert response.status_code == 200, "Deve retornar 200 mesmo com lista vazia."
        body = response.get_json()
        assert body["status"] == "success"
        assert body["patients"] == []


def test_get_all_patients_internal_error(auth_client):
    """Falha na camada de dados deve virar 500 estruturado, nao stacktrace."""
    with patch("server._pacientes") as mock_pacientes:
        mock_pacientes.return_value.listar.side_effect = Exception("Erro simulado de DB")
        response = auth_client.get("/api/all-patients")

        assert response.status_code == 500
        assert response.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /api/health  (B12 - usado pelo healthcheck do Docker)
# ---------------------------------------------------------------------------

def test_health_endpoint_is_public(client):
    """O healthcheck precisa responder sem token, senao o compose nunca sobe."""
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["service"] == "copilot-medico-api"
    assert "diarizer_loaded" in body
    # TRANSCRIPTION_PROVIDER=vosk no conftest: nenhum provedor externo (B31)
    assert body["transcription_provider"] is None
