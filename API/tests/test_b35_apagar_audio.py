"""B35 - nenhum audio fica no servidor depois da transcricao (US017-CA007).

Criterio de aceite: nenhum WAV restante apos falha simulada. Cobre o
`finally` das duas rotas (audio inteiro e em partes) em cada ponto em que
algo pode falhar, e o job diario que varre o que sobrou.
"""
import importlib
import io
import os
import runpy
import threading
import time
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from backend import audio_chunks, limpeza_audio
from backend.config import settings
from ids import DOCTOR_A
from models import ParteAudio
from repositories import ConsultaRepository, PacienteRepository, ParteAudioRepository, sessao

GRAVACAO = "gravacao-b35-0001"


@pytest.fixture(autouse=True)
def pasta(tmp_path, monkeypatch):
    pasta = tmp_path / "audio"
    monkeypatch.setattr(settings, "audio_chunks_dir", str(pasta))
    return pasta


@pytest.fixture()
def admin(auth_headers):
    return auth_headers("administrador")


@pytest.fixture()
def server():
    return importlib.import_module("server")


@pytest.fixture()
def paciente(client):
    """(paciente, consulta) do doctor-a. Depende de `client` para o banco temporario."""
    pid = PacienteRepository(sessao.obter_sessao()).criar(nome="Paciente B35", medico_id=DOCTOR_A)["id"]
    return pid, ConsultaRepository(sessao.obter_sessao()).criar(pid, "Consulta B35")


class _Transcritor:
    """Diarizador falso: guarda o caminho recebido e pode falhar."""

    def __init__(self, erro=None):
        self.erro = erro
        self.caminhos = []

    def processar_audio(self, caminho):
        self.caminhos.append(caminho)
        if self.erro:
            raise self.erro
        return {"full_text": "Médico: Bom dia", "dialogue": [
            {"role": "Médico", "role_key": "doctor", "text": "Bom dia", "speaker_id": 0}]}


def _wav(segundos=1, taxa=100):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(taxa)
        wav.writeframes(b"\x00\x00" * int(segundos * taxa))
    buffer.seek(0)
    return buffer


def _arquivos(pasta: Path):
    return sorted(p.name for p in pasta.rglob("*") if p.is_file()) if pasta.exists() else []


def _envelhecer(caminho, horas):
    antigo = time.time() - horas * 3600
    os.utime(caminho, (antigo, antigo))


def _audio_inteiro(client, headers, pid, cid, nome="consulta.wav"):
    return client.post("/api/transcribe_audio", data={
        "audio_file": (_wav(), nome), "patient_id": pid, "consultation_id": cid,
    }, content_type="multipart/form-data", headers=headers)


def _enviar_parte(client, headers, cid, seq=1, arquivo=None):
    return client.post(f"/api/consultations/{cid}/audio/chunks", data={
        "recording_id": GRAVACAO, "seq": str(seq), "audio_file": (arquivo or _wav(), f"p{seq}.wav"),
    }, content_type="multipart/form-data", headers=headers)


# ---------- rota do audio inteiro (/api/transcribe_audio) ----------

def test_audio_inteiro_fica_na_pasta_controlada_e_sai_no_sucesso(
        client, admin, paciente, server, monkeypatch, pasta):
    transcritor = _Transcritor()
    monkeypatch.setattr(server, "audio_processor", transcritor)
    pid, cid = paciente

    assert _audio_inteiro(client, admin, pid, cid).status_code == 200

    # gravado na base que o job varre, nao no /tmp do sistema
    assert Path(transcritor.caminhos[0]).parent == pasta / audio_chunks.PASTA_AVULSOS
    assert _arquivos(pasta) == []


def test_audio_inteiro_e_apagado_quando_a_transcricao_falha(
        client, admin, paciente, server, monkeypatch, pasta):
    """Provedor e Diarizador falham e a transcricao simples tambem: 500, sem WAV."""
    monkeypatch.setattr(server, "transcription_provider", _Transcritor(RuntimeError("falha simulada")))
    monkeypatch.setattr(server, "audio_processor", _Transcritor(RuntimeError("falha simulada")))
    monkeypatch.setattr(server.sr, "AudioFile", lambda caminho: (_ for _ in ()).throw(OSError("simples")))
    pid, cid = paciente

    assert _audio_inteiro(client, admin, pid, cid).status_code == 500
    assert _arquivos(pasta) == []


def test_audio_inteiro_e_apagado_quando_o_banco_falha(
        client, admin, paciente, server, monkeypatch, pasta):
    monkeypatch.setattr(server, "audio_processor", _Transcritor())

    class _RepoQuebrado:
        def adicionar(self, *args, **kwargs):
            raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(server, "_transcricoes", lambda: _RepoQuebrado())
    pid, cid = paciente

    assert _audio_inteiro(client, admin, pid, cid).status_code == 500
    assert _arquivos(pasta) == []


def test_extensao_do_nome_nao_escapa_da_pasta(client, admin, paciente, server, monkeypatch, pasta):
    transcritor = _Transcritor()
    monkeypatch.setattr(server, "audio_processor", transcritor)
    pid, cid = paciente

    _audio_inteiro(client, admin, pid, cid, nome="x.wav/../../fora")

    salvo = Path(transcritor.caminhos[0])
    assert salvo.parent == pasta / audio_chunks.PASTA_AVULSOS
    assert salvo.suffix == ".wav"


# ---------- rota em partes (B30) ----------

def test_upload_interrompido_nao_deixa_parte_parcial(client, admin, paciente, monkeypatch, pasta):
    _pid, cid = paciente
    original = audio_chunks.Path

    class _Upload:
        def save(self, destino):
            original(destino).write_bytes(b"RIFF parcial")
            raise ConnectionError("cliente desconectou")

    with pytest.raises(ConnectionError):
        audio_chunks.salvar(_Upload(), cid, GRAVACAO, 1)
    assert _arquivos(pasta) == []


def test_parte_e_apagada_quando_o_registro_no_banco_falha(
        client, admin, paciente, server, monkeypatch, pasta):
    _pid, cid = paciente

    class _RepoQuebrado:
        def registrar(self, *args, **kwargs):
            raise RuntimeError("banco fora do ar")

        def remover_anteriores_a(self, limite):
            return []

    monkeypatch.setattr(server, "_partes_audio", lambda: _RepoQuebrado())
    with pytest.raises(RuntimeError, match="banco"):  # vira 500 fora do modo de teste
        _enviar_parte(client, admin, cid)

    assert _arquivos(pasta) == []


def test_partes_sao_apagadas_quando_o_log_da_transcricao_falha(
        client, admin, paciente, server, monkeypatch, pasta):
    """Transcricao ok, mas gravar o texto falha: o audio ja saiu no finally."""
    _pid, cid = paciente
    monkeypatch.setattr(server, "audio_processor", _Transcritor())
    for seq in (1, 2):
        _enviar_parte(client, admin, cid, seq)
    assert len(_arquivos(pasta)) == 2

    class _RepoQuebrado:
        def adicionar(self, *args, **kwargs):
            raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(server, "_transcricoes", lambda: _RepoQuebrado())
    with pytest.raises(RuntimeError, match="banco"):
        client.post(f"/api/consultations/{cid}/transcribe",
                    json={"recording_id": GRAVACAO}, headers=admin)

    assert _arquivos(pasta) == []


# ---------- job diario ----------

def _parte_registrada(cid, seq, pasta, horas=0):
    caminho = pasta / str(cid) / GRAVACAO / f"{seq:04d}.wav"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(_wav().getvalue())
    ParteAudioRepository(sessao.obter_sessao()).registrar(cid, GRAVACAO, seq, str(caminho), 10, 1.0)
    if horas:
        s = sessao.obter_sessao()
        parte = s.scalars(select(ParteAudio).where(ParteAudio.seq == seq)).one()
        parte.criado_em = datetime.now(timezone.utc) - timedelta(hours=horas)
        s.commit()
        _envelhecer(caminho, horas)
    return caminho


def test_job_apaga_partes_expiradas_e_orfaos_mas_preserva_o_que_esta_em_uso(paciente, pasta):
    _pid, cid = paciente
    ttl = settings.audio_chunk_ttl_hours
    em_uso = _parte_registrada(cid, 1, pasta)                  # gravacao em andamento
    expirada = _parte_registrada(cid, 2, pasta, horas=ttl + 1)  # nunca finalizada
    orfao_velho = pasta / audio_chunks.PASTA_AVULSOS / "caiu-no-meio.wav"
    orfao_velho.parent.mkdir(parents=True)
    orfao_velho.write_bytes(b"x")
    _envelhecer(orfao_velho, ttl + 1)
    orfao_recente = pasta / audio_chunks.PASTA_AVULSOS / "transcrevendo-agora.wav"
    orfao_recente.write_bytes(b"x")

    resultado = limpeza_audio.limpar_audio_expirado()

    assert resultado == {"partes_expiradas": 1, "arquivos_orfaos": 1}
    assert em_uso.exists() and orfao_recente.exists()
    assert not expirada.exists() and not orfao_velho.exists()
    sessao.encerrar_sessao()
    assert [p.seq for p in sessao.obter_sessao().scalars(select(ParteAudio))] == [1]


def test_job_com_prazo_zero_apaga_todo_orfao(paciente, pasta):
    orfao = pasta / "qualquer" / "coisa.wav"
    orfao.parent.mkdir(parents=True)
    orfao.write_bytes(b"x")

    assert limpeza_audio.limpar_audio_expirado(ttl_horas=0)["arquivos_orfaos"] == 1
    assert _arquivos(pasta) == []


def test_job_sem_pasta_nao_falha(paciente, pasta):
    assert not pasta.exists()
    assert limpeza_audio.limpar_audio_expirado() == {"partes_expiradas": 0, "arquivos_orfaos": 0}


def test_thread_roda_ao_subir_e_para(monkeypatch):
    rodou = threading.Event()
    monkeypatch.setattr(limpeza_audio, "limpar_audio_expirado", lambda: rodou.set() or {"a": 0})
    parar = threading.Event()

    thread = limpeza_audio.iniciar_limpeza_periodica(intervalo_horas=24, parar=parar)

    assert rodou.wait(5)
    parar.set()
    thread.join(5)
    assert not thread.is_alive()


def test_thread_sobrevive_a_falha_do_job(monkeypatch, capsys):
    chamadas = []
    parar = threading.Event()

    def falha():
        chamadas.append(1)
        if len(chamadas) >= 2:
            parar.set()
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(limpeza_audio, "limpar_audio_expirado", falha)
    thread = limpeza_audio.iniciar_limpeza_periodica(intervalo_horas=1e-6, parar=parar)
    thread.join(5)

    assert len(chamadas) >= 2  # continuou depois da primeira falha
    assert "Limpeza falhou" in capsys.readouterr().out


def test_intervalo_zero_desliga_o_job():
    assert limpeza_audio.iniciar_limpeza_periodica(intervalo_horas=0) is None


def test_script_de_cron(paciente, pasta, capsys):
    orfao = pasta / "x.wav"
    pasta.mkdir()
    orfao.write_bytes(b"x")
    modulo = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "limpar_audio.py"))
    assert modulo["main"](["--ttl-horas", "0"]) == 0
    assert "arquivos orfaos: 1" in capsys.readouterr().out
    assert not orfao.exists()
