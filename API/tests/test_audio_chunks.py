"""B30 - audio da consulta enviado em partes (US017-CA003).

POST /api/consultations/<id>/audio/chunks recebe cada parte com a sua
sequencia; POST /api/consultations/<id>/transcribe junta tudo na ordem.
Criterio de aceite: 3 partes e um reenvio; a consulta continua se uma parte
falhar; o audio sai do servidor depois da transcricao.
"""
import importlib
import io
import uuid
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from backend import auth_decorators
from backend.config import settings
from ids import DOCTOR_A, DOCTOR_B
from models import ParteAudio
from repositories import ConsultaRepository, PacienteRepository, ParteAudioRepository, sessao

GRAVACAO = "gravacao-teste-0001"


def _login(monkeypatch, profile="medico", user_id=DOCTOR_A):
    def fake_get_user_from_token(token):
        if token != "valid-token":
            raise auth_decorators.AuthError("Token invalido", 401)
        return (
            {"id": user_id, "email": "user@example.com", "name": "Usuario Teste",
             "profiles": [profile], "active": True},
            {"profile": profile},
        )

    monkeypatch.setattr(auth_decorators, "get_user_from_token", fake_get_user_from_token)
    return {"Authorization": "Bearer valid-token"}


@pytest.fixture()
def medico(monkeypatch):
    return _login(monkeypatch)


@pytest.fixture()
def consulta(client):
    """Consulta de um paciente do doctor-a. Depende de `client` para o banco temporario."""
    pid = PacienteRepository(sessao.obter_sessao()).criar(nome="Paciente Teste", medico_id=DOCTOR_A)["id"]
    return ConsultaRepository(sessao.obter_sessao()).criar(pid, "Consulta Teste")


@pytest.fixture(autouse=True)
def pasta_das_partes(tmp_path, monkeypatch):
    pasta = tmp_path / "partes"
    monkeypatch.setattr(settings, "audio_chunks_dir", str(pasta))
    return pasta


class _TranscritorFalso:
    """No lugar do Diarizador: o "texto" de cada parte e a sua duracao, o que
    permite conferir a ordem e qual versao de uma parte foi transcrita."""

    def __init__(self, falha_em_s=None, diarizado=False):
        self.falha_em_s = falha_em_s
        self.diarizado = diarizado

    def processar_audio(self, caminho):
        with wave.open(caminho, "rb") as wav:
            segundos = round(wav.getnframes() / wav.getframerate())
        if segundos == self.falha_em_s:
            raise RuntimeError("falha simulada")
        texto = f"fala de {segundos}s"
        dialogo = [{"role": "Médico", "role_key": "doctor", "text": texto, "speaker_id": 0}]
        return {"full_text": texto, "dialogue": dialogo if self.diarizado else []}


@pytest.fixture()
def transcritor(monkeypatch):
    def _instalar(**kwargs):
        monkeypatch.setattr(importlib.import_module("server"), "audio_processor",
                            _TranscritorFalso(**kwargs))
    _instalar()
    return _instalar


def _wav(segundos, taxa=100):
    """WAV PCM valido de `segundos` de silencio (taxa baixa: arquivo pequeno)."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(taxa)
        wav.writeframes(b"\x00\x00" * int(segundos * taxa))
    buffer.seek(0)
    return buffer


def _enviar(client, headers, cid, seq, segundos=1, gravacao=GRAVACAO, arquivo=None):
    dados = {"recording_id": gravacao, "seq": str(seq)}
    if arquivo is not False:
        dados["audio_file"] = (arquivo or _wav(segundos), f"parte-{seq}.wav")
    return client.post(f"/api/consultations/{cid}/audio/chunks", data=dados,
                       content_type="multipart/form-data", headers=headers)


def _transcrever(client, headers, cid, gravacao=GRAVACAO, **extra):
    return client.post(f"/api/consultations/{cid}/transcribe",
                       json={"recording_id": gravacao, **extra}, headers=headers)


def _arquivos(pasta: Path):
    return sorted(p.name for p in pasta.rglob("*.wav"))


def _linhas():
    sessao.encerrar_sessao()
    return list(sessao.obter_sessao().scalars(select(ParteAudio).order_by(ParteAudio.seq)))


# ---------- criterio de aceite: 3 partes e um reenvio ----------

def test_tres_partes_e_um_reenvio_viram_uma_transcricao_em_ordem(
        client, medico, consulta, transcritor, pasta_das_partes):
    r1 = _enviar(client, medico, consulta, seq=1, segundos=1)
    r2 = _enviar(client, medico, consulta, seq=2, segundos=2)
    r3 = _enviar(client, medico, consulta, seq=3, segundos=3)
    # reenvio da parte 2 (a extensao repete o envio quando nao recebe a resposta)
    reenvio = _enviar(client, medico, consulta, seq=2, segundos=4)

    assert [r.status_code for r in (r1, r2, r3, reenvio)] == [202, 202, 202, 202]
    assert r2.get_json()["replaced"] is False
    assert reenvio.get_json()["replaced"] is True
    assert reenvio.get_json()["received"] == [1, 2, 3]
    # o reenvio substitui: continua uma linha e um arquivo por sequencia
    assert [(p.seq, p.duracao_s) for p in _linhas()] == [(1, 1.0), (2, 4.0), (3, 3.0)]
    assert len(_arquivos(pasta_das_partes)) == 3

    resp = _transcrever(client, medico, consulta, total_chunks=3)
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["is_error"] is False
    assert body["transcription"] == "fala de 1s\nfala de 4s\nfala de 3s"
    assert body["chunks"] == {"received": [1, 2, 3], "missing": [], "failed": []}
    assert body["log_entry"]["consultation_id"] == consulta
    assert body["log_entry"]["duration"] == "0:08"


def test_partes_fora_de_ordem_sao_transcritas_pela_sequencia(client, medico, consulta, transcritor):
    for seq in (3, 1, 2):
        assert _enviar(client, medico, consulta, seq=seq, segundos=seq).status_code == 202

    body = _transcrever(client, medico, consulta).get_json()

    assert body["transcription"] == "fala de 1s\nfala de 2s\nfala de 3s"


def test_resposta_da_parte_devolve_os_metadados(client, medico, consulta):
    body = _enviar(client, medico, consulta, seq=1, segundos=2).get_json()

    assert body["status"] == "accepted"
    assert body["consultation_id"] == consulta
    assert body["recording_id"] == GRAVACAO
    assert body["seq"] == 1
    assert body["duration"] == 2.0
    assert body["size_bytes"] > 44
    assert body["received"] == [1]


# ---------- a consulta continua se uma parte falhar ----------

def test_parte_que_nao_chegou_nao_impede_a_transcricao(client, medico, consulta, transcritor):
    _enviar(client, medico, consulta, seq=1, segundos=1)
    _enviar(client, medico, consulta, seq=3, segundos=3)  # a 2 se perdeu no caminho

    resp = _transcrever(client, medico, consulta, total_chunks=3)
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["is_error"] is False
    assert body["transcription"] == "fala de 1s\nfala de 3s"
    assert body["chunks"] == {"received": [1, 3], "missing": [2], "failed": []}
    assert body["log_entry"]["audio"]["chunks"]["missing"] == [2]


def test_parte_que_falha_na_transcricao_e_pulada(client, medico, consulta, transcritor):
    transcritor(falha_em_s=2)
    for seq in (1, 2, 3):
        _enviar(client, medico, consulta, seq=seq, segundos=seq)

    body = _transcrever(client, medico, consulta, total_chunks=3).get_json()

    assert body["is_error"] is False
    assert body["transcription"] == "fala de 1s\nfala de 3s"
    assert body["chunks"]["failed"] == [2]


def test_nenhuma_parte_transcrita_responde_is_error_sem_salvar(client, medico, consulta, transcritor):
    transcritor(falha_em_s=1)
    _enviar(client, medico, consulta, seq=1, segundos=1)

    body = _transcrever(client, medico, consulta).get_json()

    assert body["is_error"] is True
    assert "log_entry" not in body
    pid = ConsultaRepository(sessao.obter_sessao()).paciente_da_consulta(consulta)
    logs = client.get(f"/api/patients/{pid}/transcription-log", headers=medico).get_json()["logs"]
    assert logs == []


def test_turnos_das_partes_sao_concatenados(client, medico, consulta, transcritor):
    transcritor(diarizado=True)
    for seq in (1, 2):
        _enviar(client, medico, consulta, seq=seq, segundos=seq)

    log = _transcrever(client, medico, consulta).get_json()["log_entry"]

    assert [turno["text"] for turno in log["dialogue"]] == ["fala de 1s", "fala de 2s"]
    assert {turno["role_key"] for turno in log["dialogue"]} == {"doctor"}


def test_transcricao_fica_no_log_do_paciente(client, medico, consulta, transcritor):
    _enviar(client, medico, consulta, seq=1, segundos=1)
    _transcrever(client, medico, consulta)

    pid = ConsultaRepository(sessao.obter_sessao()).paciente_da_consulta(consulta)
    logs = client.get(f"/api/patients/{pid}/transcription-log", headers=medico).get_json()["logs"]

    assert [(log["text"], log["consultation_id"]) for log in logs] == [("fala de 1s", consulta)]
    assert logs[0]["audio"]["persisted"] is False


# ---------- o audio nao fica no servidor (US017-CA007) ----------

def test_audio_e_apagado_depois_da_transcricao(client, medico, consulta, transcritor, pasta_das_partes):
    for seq in (1, 2, 3):
        _enviar(client, medico, consulta, seq=seq)
    assert len(_arquivos(pasta_das_partes)) == 3

    _transcrever(client, medico, consulta)

    assert _arquivos(pasta_das_partes) == []
    assert _linhas() == []
    # as pastas da consulta/gravacao tambem saem
    assert list(pasta_das_partes.iterdir()) == []
    # e nao ha o que transcrever de novo
    assert _transcrever(client, medico, consulta).status_code == 404


def test_audio_e_apagado_mesmo_quando_a_transcricao_falha(
        client, medico, consulta, transcritor, pasta_das_partes):
    transcritor(falha_em_s=1)
    _enviar(client, medico, consulta, seq=1, segundos=1)

    _transcrever(client, medico, consulta)

    assert _arquivos(pasta_das_partes) == []
    assert _linhas() == []


def test_transcrever_so_apaga_a_gravacao_pedida(client, medico, consulta, transcritor, pasta_das_partes):
    _enviar(client, medico, consulta, seq=1, gravacao="gravacao-aaaa")
    _enviar(client, medico, consulta, seq=1, gravacao="gravacao-bbbb")

    _transcrever(client, medico, consulta, gravacao="gravacao-aaaa")

    assert [p.gravacao_id for p in _linhas()] == ["gravacao-bbbb"]
    assert len(_arquivos(pasta_das_partes)) == 1


def test_partes_de_gravacao_abandonada_sao_apagadas_no_proximo_envio(
        client, medico, consulta, pasta_das_partes):
    _enviar(client, medico, consulta, seq=1, gravacao="gravacao-antiga")
    s = sessao.obter_sessao()
    antiga = s.scalars(select(ParteAudio)).one()
    antiga.criado_em = datetime.now(timezone.utc) - timedelta(hours=settings.audio_chunk_ttl_hours + 1)
    s.commit()

    _enviar(client, medico, consulta, seq=1, gravacao="gravacao-nova1")

    assert [p.gravacao_id for p in _linhas()] == ["gravacao-nova1"]
    assert len(_arquivos(pasta_das_partes)) == 1


# ---------- validacao ----------

def test_parte_sem_arquivo_400(client, medico, consulta):
    assert _enviar(client, medico, consulta, seq=1, arquivo=False).status_code == 400


@pytest.mark.parametrize("seq", ["0", "-1", "abc", "", "1001"])
def test_seq_invalido_400(client, medico, consulta, seq, pasta_das_partes):
    resp = _enviar(client, medico, consulta, seq=seq)

    assert resp.status_code == 400
    assert not pasta_das_partes.exists() or _arquivos(pasta_das_partes) == []


@pytest.mark.parametrize("gravacao", ["", "curto", "../../etc/passwd", "com espaco no meio"])
def test_recording_id_invalido_400(client, medico, consulta, gravacao):
    assert _enviar(client, medico, consulta, seq=1, gravacao=gravacao).status_code == 400
    assert _transcrever(client, medico, consulta, gravacao=gravacao).status_code == 400


def test_arquivo_que_nao_e_wav_400_e_nao_fica_em_disco(client, medico, consulta, pasta_das_partes):
    resp = _enviar(client, medico, consulta, seq=1, arquivo=io.BytesIO(b"isto nao e um wav"))

    assert resp.status_code == 400
    assert _arquivos(pasta_das_partes) == []
    assert _linhas() == []


def test_parte_com_mais_de_cinco_minutos_400(client, medico, consulta, pasta_das_partes):
    resp = _enviar(client, medico, consulta, seq=1, segundos=5 * 60 + 6)

    assert resp.status_code == 400
    assert "5 min" in resp.get_json()["message"]
    assert _arquivos(pasta_das_partes) == []


def test_parte_de_exatos_cinco_minutos_e_aceita(client, medico, consulta):
    assert _enviar(client, medico, consulta, seq=1, segundos=5 * 60).status_code == 202


def test_parte_acima_do_tamanho_maximo_413(client, medico, consulta, monkeypatch, pasta_das_partes):
    monkeypatch.setattr(settings, "audio_chunk_max_mb", 0)

    assert _enviar(client, medico, consulta, seq=1).status_code == 413
    assert _arquivos(pasta_das_partes) == []


def test_parte_vazia_400(client, medico, consulta, pasta_das_partes):
    assert _enviar(client, medico, consulta, seq=1, segundos=0).status_code == 400
    assert _arquivos(pasta_das_partes) == []


def test_total_chunks_invalido_400(client, medico, consulta):
    _enviar(client, medico, consulta, seq=1)

    resp = _transcrever(client, medico, consulta, total_chunks="muitas")

    assert resp.status_code == 400
    assert "total_chunks" in resp.get_json()["message"]
    # pedido recusado na validacao: as partes continuam guardadas para uma nova tentativa
    assert [p.seq for p in _linhas()] == [1]


def test_transcrever_sem_json_400(client, medico, consulta):
    resp = client.post(f"/api/consultations/{consulta}/transcribe", data="x", headers=medico)

    assert resp.status_code == 400


def test_transcrever_gravacao_sem_partes_404(client, medico, consulta):
    assert _transcrever(client, medico, consulta).status_code == 404


def test_consulta_inexistente_404(client, medico):
    fantasma = str(uuid.uuid4())

    assert _enviar(client, medico, fantasma, seq=1).status_code == 404
    assert _enviar(client, medico, "nao-e-uuid", seq=1).status_code == 404
    assert _transcrever(client, medico, fantasma).status_code == 404


# ---------- 401/403 e isolamento por medico ----------

def test_rotas_exigem_token_401(client, consulta):
    assert _enviar(client, {}, consulta, seq=1).status_code == 401
    assert _transcrever(client, {}, consulta).status_code == 401


def test_perfil_sem_permissao_403(client, consulta, monkeypatch):
    recepcao = _login(monkeypatch, profile="recepcao", user_id="user-x")

    assert _enviar(client, recepcao, consulta, seq=1).status_code == 403
    assert _transcrever(client, recepcao, consulta).status_code == 403


def test_outro_medico_nao_envia_nem_transcreve_403(client, consulta, monkeypatch, transcritor):
    dono = _login(monkeypatch, user_id=DOCTOR_A)
    assert _enviar(client, dono, consulta, seq=1).status_code == 202

    outro = _login(monkeypatch, user_id=DOCTOR_B)

    assert _enviar(client, outro, consulta, seq=2).status_code == 403
    assert _transcrever(client, outro, consulta).status_code == 403
    # a parte do dono continua la, intacta
    assert [p.seq for p in _linhas()] == [1]


# ---------- repositorio ----------

def test_repositorio_ignora_consulta_inexistente(temp_db_file):
    repo = ParteAudioRepository(sessao.obter_sessao())

    assert repo.registrar(str(uuid.uuid4()), GRAVACAO, 1, "/tmp/x.wav", 10, 1.0) == (None, None)
    assert repo.listar("nao-e-uuid", GRAVACAO) == []
    assert repo.remover("nao-e-uuid", GRAVACAO) == []
