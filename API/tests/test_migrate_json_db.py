"""B21 - migracao de patients_db.json / users_db.json para o banco.

Os dados de entrada reproduzem os formatos que o patient_db.py e o
auth_service gravavam (ver o patients_db.json de exemplo removido no B14).
"""
import json
import sys
import uuid
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from ids import TEST_USER_ID
from repositories import (
    ConsultaRepository,
    DadoExtensaoRepository,
    MedicoRepository,
    MensagemRepository,
    PacienteRepository,
    TranscricaoRepository,
    sessao,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import migrate_json_db as mig  # noqa: E402

ADMIN = "11111111-1111-4111-8111-111111111111"
MEDICO = "22222222-2222-4222-8222-222222222222"
PENDENTE = "33333333-3333-4333-8333-333333333333"
PAC = "44444444-4444-4444-8444-444444444444"
CONS = "55555555-5555-4555-8555-555555555555"


def _msg(role, text, ts):
    return {"role": role, "parts": [{"text": text}], "timestamp": ts}


def _usuarios():
    return [
        {"id": ADMIN, "email": "admin@exemplo.local", "name": "Admin",
         "password_hash": generate_password_hash("SenhaAdmin1!"), "profiles": ["administrador"],
         "active": True, "created_at": "2026-01-01T00:00:00+00:00"},
        {"id": MEDICO, "email": "Dra@Exemplo.local", "name": "Dra. Ana",
         "password_hash": generate_password_hash("SenhaMedica1!"), "profiles": ["medico"],
         "active": True, "crm": "CRM-1", "specialty": "Clinica", "approval_status": "approved",
         "approved_at": "2026-01-02T10:00:00+00:00", "approved_by": ADMIN},
        {"id": PENDENTE, "email": "pendente@exemplo.local", "name": "Dr. Pendente",
         "password_hash": "h", "profiles": ["medico"], "active": False, "approval_status": "pending"},
    ]


def _pacientes():
    return {
        PAC: {
            "name": "Maria", "doctor_id": MEDICO, "created_by": ADMIN,
            "created_at": "2026-02-01T09:00:00",
            "consultations": [{
                "id": CONS, "title": "Primeira Consulta", "date": "2026-02-01T09:00:00",
                "chat_history": [
                    _msg("user", "pergunta", "2026-02-01T09:01:00"),
                    # mesmo timestamp: a ordem do JSON tem que ser mantida
                    _msg("model", "resposta", "2026-02-01T09:01:00"),
                    _msg("user", "fora de ordem", "2026-02-01T08:00:00"),
                    _msg("sistema", "papel invalido", "2026-02-01T09:02:00"),
                ],
            }],
            "chat_history": [_msg("user", "chat antigo do paciente", "2025-12-01T10:00:00")],
            "extension_data": [{
                "id": str(uuid.uuid4()), "consultation_id": CONS, "source": "extension",
                "source_url": "https://pep.example/atendimento", "type": "extracted_data",
                "content": {"peso": "70", "alergias": ["dipirona"]}, "created_at": "2026-02-01T09:05:00",
            }],
            "transcription_log": [{
                "id": str(uuid.uuid4()), "consultation_id": None, "source": "extension",
                "text": "Bom dia", "dialogue": [{"speaker": "medico", "text": "Bom dia"}],
                "duration": "2:05", "audio": {"persisted": False, "filename": "a.wav"},
                "created_at": "2026-02-01T09:10:00",
            }],
        },
        "legado-sem-uuid": {"name": "Carlos", "chat_history": [], "consultations": [
            {"id": "consulta-sem-uuid", "title": "Antiga", "date": "2025-07-05T10:00:00", "chat_history": []},
        ]},
        "paciente_abc": {"name": "João Silva", "chat_history": [], "consultations": [
            {"id": str(uuid.uuid4()), "title": "Consulta Antiga 1", "date": "2025-07-04T19:17:38", "chat_history": []},
        ]},
    }


@pytest.fixture()
def s(temp_db_file):
    return sessao.obter_sessao()


def _migrar(s, **kw):
    rel = mig.migrar(s, _pacientes(), _usuarios(), **kw)
    s.commit()
    return rel


# --- usuarios -----------------------------------------------------------------

def test_usuarios_preservam_id_senha_e_aprovacao(s):
    from backend import auth_service

    _migrar(s)

    medica = MedicoRepository(s).obter(MEDICO)
    assert medica["email"] == "dra@exemplo.local"
    assert medica["approval_status"] == "approved"
    assert medica["approved_by"] == ADMIN
    assert medica["crm"] == "CRM-1" and medica["specialty"] == "Clinica"
    assert MedicoRepository(s).obter(PENDENTE)["approval_status"] == "pending"
    # Mesmo hash de senha: o login continua funcionando com a senha antiga.
    assert auth_service.authenticate_user("dra@exemplo.local", "SenhaMedica1!")["id"] == MEDICO
    assert auth_service.authenticate_user("pendente@exemplo.local", "x") is None


def test_usuario_com_email_ja_no_banco_e_reaproveitado(s):
    usuarios = _usuarios()
    usuarios[0]["email"] = "doctor@example.com"  # ja cadastrado pelo conftest (TEST_USER_ID)
    pacientes = _pacientes()
    pacientes[PAC]["doctor_id"] = ADMIN

    rel = mig.migrar(s, pacientes, usuarios)
    s.commit()

    assert rel.existentes["usuarios"] == 1
    assert MedicoRepository(s).obter(ADMIN) is None
    # A referencia ao usuario antigo aponta para quem ja estava no banco.
    assert PacienteRepository(s).obter(PAC)["doctor_id"] == TEST_USER_ID


# --- pacientes ----------------------------------------------------------------

def test_paciente_preserva_id_nome_e_medico(s):
    _migrar(s)

    paciente = PacienteRepository(s).obter(PAC)
    assert paciente["name"] == "Maria"
    assert paciente["doctor_id"] == MEDICO
    assert paciente["created_by"] == ADMIN
    assert paciente["created_at"] == "2026-02-01T09:00:00+00:00"


def test_seed_e_descartado_e_id_nao_uuid_e_convertido(s):
    rel = _migrar(s)

    assert any("paciente_abc" in d for d in rel.descartados)
    assert PacienteRepository(s).obter(str(mig._uuid("paciente_abc", "paciente"))) is None
    novo = rel.ids_convertidos["legado-sem-uuid"]
    assert PacienteRepository(s).obter(novo)["name"] == "Carlos"
    assert [c["title"] for c in ConsultaRepository(s).listar(novo)] == ["Antiga"]


def test_manter_seed(s):
    rel = _migrar(s, manter_seed=True)

    assert rel.descartados == []
    assert PacienteRepository(s).obter(rel.ids_convertidos["paciente_abc"])["name"] == "João Silva"


def test_mensagens_na_ordem_do_json(s):
    rel = _migrar(s)

    historico = MensagemRepository(s).historico(CONS)
    assert [(m["role"], m["parts"][0]["text"]) for m in historico] == [
        ("user", "pergunta"), ("model", "resposta"), ("user", "fora de ordem"),
    ]
    assert any("sistema" in a for a in rel.avisos)


def test_chat_solto_do_paciente_vira_consulta_legada(s):
    _migrar(s)

    consultas = ConsultaRepository(s).listar(PAC)
    legada = next(c for c in consultas if c["title"] == mig.TITULO_HISTORICO_LEGADO)
    assert [m["parts"][0]["text"] for m in legada["chat_history"]] == ["chat antigo do paciente"]
    # Mais antiga primeiro: o chat legado e anterior a "Primeira Consulta".
    assert consultas[0]["title"] == mig.TITULO_HISTORICO_LEGADO


def test_extensao_e_transcricao(s):
    _migrar(s)

    dado = DadoExtensaoRepository(s).listar(PAC)[0]
    assert dado["content"] == {"peso": "70", "alergias": ["dipirona"]}
    assert dado["consultation_id"] == CONS
    assert dado["source_url"] == "https://pep.example/atendimento"
    transcricao = TranscricaoRepository(s).listar(PAC)[0]
    assert transcricao["duration"] == "2:05"
    assert transcricao["dialogue"] == [{"speaker": "medico", "text": "Bom dia"}]
    assert transcricao["audio"]["filename"] == "a.wav"


def test_medico_inexistente_vira_aviso(s):
    pacientes = _pacientes()
    pacientes[PAC]["doctor_id"] = "medico-que-sumiu"

    rel = mig.migrar(s, pacientes, _usuarios())

    assert PacienteRepository(s).obter(PAC)["doctor_id"] is None
    assert any("medico-que-sumiu" in a for a in rel.avisos)


# --- idempotencia e conferencia ---------------------------------------------------

def test_rodar_duas_vezes_nao_duplica(s):
    _migrar(s)
    rel = _migrar(s)

    assert rel.inseridos == {}
    assert rel.existentes == {"usuarios": 3, "pacientes": 2}
    assert len(ConsultaRepository(s).listar(PAC)) == 2
    assert len(MensagemRepository(s).historico(CONS)) == 3


def test_conferencia_passa_e_detecta_perda(s):
    pacientes = _pacientes()
    rel = mig.migrar(s, pacientes, _usuarios())
    assert mig.conferir(s, pacientes, rel) == []

    pacientes[PAC]["consultations"][0]["chat_history"].append(_msg("user", "nova", "2026-03-01T00:00:00"))
    assert any(CONS in p for p in mig.conferir(s, pacientes, rel))


# --- linha de comando ---------------------------------------------------------

def _arquivos(tmp_path):
    pacientes = tmp_path / "patients_db.json"
    usuarios = tmp_path / "users_db.json"
    pacientes.write_text(json.dumps(_pacientes()), encoding="utf-8")
    usuarios.write_text(json.dumps({"users": _usuarios()}), encoding="utf-8")
    return ["--pacientes", str(pacientes), "--usuarios", str(usuarios),
            "--db-url", f"sqlite:///{(tmp_path / 'destino.db').as_posix()}"]


def _contar_pacientes(url):
    sessao.configurar(url)
    try:
        return len(PacienteRepository(sessao.obter_sessao()).listar())
    finally:
        sessao.descartar()


def test_cli_dry_run_nao_grava_e_real_grava(tmp_path, capsys):
    args = _arquivos(tmp_path)
    url = args[-1]

    assert mig.main(args + ["--dry-run"]) == 0
    assert "Nada foi gravado" in capsys.readouterr().out
    assert _contar_pacientes(url) == 0

    assert mig.main(args) == 0
    saida = capsys.readouterr().out
    assert "tudo o que estava no JSON esta no banco" in saida
    assert "paciente_abc" in saida
    assert _contar_pacientes(url) == 2


def test_cli_sem_arquivos_nao_falha(tmp_path):
    url = f"sqlite:///{(tmp_path / 'vazio.db').as_posix()}"

    assert mig.main(["--pacientes", str(tmp_path / "x.json"), "--usuarios",
                     str(tmp_path / "y.json"), "--db-url", url]) == 0
