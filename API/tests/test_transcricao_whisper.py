"""B32: provedor Whisper via Groq, selecionavel por TRANSCRIPTION_PROVIDER.

A Groq nao e chamada de verdade: `urlopen` e substituido por um falso.
"""
import io
import json
import types
import urllib.error

import pytest

from backend.transcription import TranscriptionError, TranscriptionProvider, obter_provedor
from backend.transcription.gemini_audio import GeminiAudioProvider
from backend.transcription import whisper as whisper_mod
from backend.transcription.whisper import WhisperGroqProvider

RESPOSTA_GROQ = {
    "text": " bom dia, o que houve? estou com dor de cabeça.",
    "duration": 7.5,
    "segments": [
        {"start": 0.0, "end": 2.4, "text": " bom dia, o que houve?"},
        {"start": 2.4, "end": 7.5, "text": " estou com dor de cabeça."},
        {"start": 7.5, "end": 7.5, "text": "  "},
    ],
}


def _config(**valores):
    base = {"transcription_provider": "", "groq_api_key": "", "groq_whisper_model": "whisper-large-v3",
            "gemini_api_key": "", "gemini_audio_model": ""}
    base.update(valores)
    return types.SimpleNamespace(**base)


class _RespostaFalsa(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@pytest.fixture()
def audio(tmp_path):
    caminho = tmp_path / "consulta.wav"
    caminho.write_bytes(b"RIFF....fake")
    return str(caminho)


@pytest.fixture()
def groq_falsa(monkeypatch):
    chamadas = []

    def fake_urlopen(req, timeout=None):
        chamadas.append(req)
        return _RespostaFalsa(json.dumps(RESPOSTA_GROQ).encode())

    monkeypatch.setattr(whisper_mod.urllib.request, "urlopen", fake_urlopen)
    return chamadas


# ---------- escolha do provedor pelo .env ----------

def test_sem_variavel_usa_o_gemini_e_nao_o_whisper():
    """O padrao e o Gemini audio (B31); o Whisper so entra com a flag."""
    provedor = obter_provedor(_config(gemini_api_key="g", groq_api_key="gsk_teste"))
    assert isinstance(provedor, GeminiAudioProvider)


def test_whisper_com_chave_seleciona_groq():
    provedor = obter_provedor(_config(transcription_provider=" Whisper ", groq_api_key="gsk_teste"))
    assert isinstance(provedor, WhisperGroqProvider)
    assert provedor.nome == "whisper"
    assert provedor.modelo == "whisper-large-v3"


def test_whisper_sem_chave_volta_ao_padrao():
    provedor = obter_provedor(_config(transcription_provider="whisper", gemini_api_key="g"))
    assert isinstance(provedor, GeminiAudioProvider)


def test_whisper_sem_nenhuma_chave_fica_no_diarizador():
    assert obter_provedor(_config(transcription_provider="whisper")) is None


def test_provedor_desconhecido_volta_ao_padrao():
    provedor = obter_provedor(_config(transcription_provider="xyz", groq_api_key="k", gemini_api_key="g"))
    assert isinstance(provedor, GeminiAudioProvider)


def test_mesmo_contrato_que_o_gemini():
    """B32: Whisper e Gemini implementam a mesma interface do B31."""
    assert issubclass(WhisperGroqProvider, TranscriptionProvider)
    assert issubclass(GeminiAudioProvider, TranscriptionProvider)


# ---------- contrato do provedor ----------

def test_mesmo_contrato_do_diarizador(audio, groq_falsa):
    resultado = WhisperGroqProvider(api_key="gsk_teste").processar_audio(audio)

    assert set(resultado) == {"full_text", "dialogue", "speakers_count", "duration"}
    assert resultado["duration"] == 7.5
    assert resultado["speakers_count"] == 1
    assert len(resultado["dialogue"]) == 2  # segmento vazio descartado
    for turno in resultado["dialogue"]:
        assert {"role", "role_key", "text", "speaker_id"} <= set(turno)
        assert turno["role_key"] == "unknown"
    assert resultado["dialogue"][0]["text"] == "Bom dia, o que houve?"
    assert resultado["dialogue"][1]["start"] == 2.4
    assert resultado["full_text"].splitlines() == [
        "Falante não identificado: Bom dia, o que houve?",
        "Falante não identificado: Estou com dor de cabeça.",
    ]


def test_requisicao_para_a_groq(audio, groq_falsa):
    WhisperGroqProvider(api_key="gsk_teste").processar_audio(audio)

    req = groq_falsa[0]
    assert req.full_url == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer gsk_teste"
    corpo = req.data
    assert b'name="model"\r\n\r\nwhisper-large-v3' in corpo
    assert b'name="language"\r\n\r\npt' in corpo
    assert b'name="response_format"\r\n\r\nverbose_json' in corpo
    assert b'filename="consulta.wav"' in corpo
    assert b"RIFF....fake" in corpo


def test_resposta_sem_segmentos_usa_o_texto(audio, monkeypatch):
    monkeypatch.setattr(
        whisper_mod.urllib.request, "urlopen",
        lambda req, timeout=None: _RespostaFalsa(json.dumps({"text": "tudo bem", "duration": 3}).encode()),
    )
    resultado = WhisperGroqProvider(api_key="k").processar_audio(audio)
    assert resultado["dialogue"][0]["text"] == "Tudo bem"
    assert resultado["duration"] == 3.0


def test_erro_http_vira_transcription_error(audio, monkeypatch):
    def falha(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(whisper_mod.urllib.request, "urlopen", falha)
    with pytest.raises(TranscriptionError, match="401"):
        WhisperGroqProvider(api_key="errada").processar_audio(audio)
