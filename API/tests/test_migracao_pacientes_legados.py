"""
Testes da B68 / bug D-24: pacientes sem medico ficavam invisiveis para
qualquer medico em /api/all-patients.

Desde o B20 a migracao roda sobre o banco relacional
(PacienteRepository.atribuir_medico_aos_sem_medico). O seed "paciente_abc"
nao existe mais no banco: o ID nao e UUID e a rota o trata como inexistente.
"""
import pytest

from ids import DOCTOR_A, DOCTOR_B
from migrate_legacy_patients import migrate_legacy_patients
from repositories import MedicoNaoEncontrado, PacienteRepository, sessao


def _pacientes():
    return PacienteRepository(sessao.obter_sessao())


def _seed_sem_medico():
    """Dois pacientes sem medico, como os legados do patients_db.json."""
    return sorted(_pacientes().criar(nome=nome)["id"] for nome in ("Maria", "Carlos"))


def _login_as(monkeypatch, user_id, profile="medico"):
    """Faz o servidor aceitar um token falso, como se `user_id` estivesse logado."""
    from backend import auth_decorators

    def fake_get_user_from_token(token):
        user = {
            "id": user_id,
            "email": f"{user_id}@example.com",
            "name": user_id,
            "profiles": [profile],
            "active": True,
        }
        return user, {"profile": profile}

    monkeypatch.setattr(auth_decorators, "get_user_from_token", fake_get_user_from_token)
    return {"Authorization": "Bearer qualquer-token"}


# --- Funcao de migracao --------------------------------------------------

def test_migrate_assigns_patients_without_doctor(temp_db_file):
    legados = _seed_sem_medico()

    atribuidos = migrate_legacy_patients(DOCTOR_A)

    assert sorted(atribuidos) == legados
    assert all(_pacientes().obter(pid)["doctor_id"] == DOCTOR_A for pid in legados)


def test_migrate_is_idempotent(temp_db_file):
    _seed_sem_medico()
    migrate_legacy_patients(DOCTOR_A)

    assert migrate_legacy_patients(DOCTOR_A) == []


def test_migrate_dry_run_does_not_write(temp_db_file):
    legados = _seed_sem_medico()

    atribuidos = migrate_legacy_patients(DOCTOR_A, dry_run=True)

    assert sorted(atribuidos) == legados
    assert all(_pacientes().obter(pid)["doctor_id"] is None for pid in legados)


def test_migrate_keeps_patients_that_already_have_a_doctor(temp_db_file):
    dono = _pacientes().criar(nome="Ana", medico_id=DOCTOR_B)["id"]
    legado = _pacientes().criar(nome="Maria")["id"]

    assert migrate_legacy_patients(DOCTOR_A) == [legado]
    assert _pacientes().obter(dono)["doctor_id"] == DOCTOR_B


@pytest.mark.parametrize("doctor_id", ["", "doc-1", "00000000-0000-4000-8000-0000000000ff"])
def test_migrate_requires_existing_doctor(temp_db_file, doctor_id):
    with pytest.raises(MedicoNaoEncontrado):
        migrate_legacy_patients(doctor_id)


def test_legacy_seed_id_is_not_found(client, temp_db_file, monkeypatch):
    headers = _login_as(monkeypatch, DOCTOR_A, profile="administrador")

    response = client.get("/api/patients/paciente_abc/consultations", headers=headers)

    assert response.status_code == 404


# --- D-24 pela rota, do ponto de vista do medico -------------------------

def test_d24_doctor_sees_legacy_patients_only_after_migration(client, temp_db_file, monkeypatch):
    legados = _seed_sem_medico()
    headers = _login_as(monkeypatch, DOCTOR_A)

    # Antes da migracao: o bug D-24 (medico nao enxerga nenhum paciente sem medico).
    before = client.get("/api/all-patients", headers=headers)
    assert before.status_code == 200
    assert before.get_json()["patients"] == []

    migrate_legacy_patients(DOCTOR_A)

    after = client.get("/api/all-patients", headers=headers)
    assert after.status_code == 200
    assert sorted(patient["id"] for patient in after.get_json()["patients"]) == legados


def test_migrated_patients_are_not_visible_to_other_doctors(client, temp_db_file, monkeypatch):
    _seed_sem_medico()
    migrate_legacy_patients(DOCTOR_A)
    headers = _login_as(monkeypatch, DOCTOR_B)

    response = client.get("/api/all-patients", headers=headers)

    assert response.status_code == 200
    assert response.get_json()["patients"] == []
