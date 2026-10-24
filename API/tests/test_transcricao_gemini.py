"""B31: TranscriptionProvider e Gemini audio com marcacao de falantes.

O Gemini nao e chamado de verdade: o SDK `google.generativeai` e trocado por
um falso injetado no provedor. O audio e a fixture real do eval (B37), entao a
duracao e o envio dos bytes sao conferidos com um WAV de verdade.

Para rodar contra a API real (gasta cota da chave):
    COPMED_GEMINI_REAL=1 GEMINI_API_KEY=... pytest tests/test_transcricao_gemini.py -k real
"""
import io
import json
import os
import pathlib
import types
import wave

import pytest

from backend.transcription import TranscriptionError, TranscriptionProvider, obter_provedor
from backend.transcription import gemini_audio
from backend.transcription.gemini_audio import GeminiAudioProvider, converter_turnos

# Lida na importacao: a fixture env_for_config troca GEMINI_API_KEY por um falso.
CHAVE_REAL = os.environ.get("GEMINI_API_KEY", "") if os.environ.get("COPMED_GEMINI_REAL") == "1" else ""

FIXTURE = pathlib.Path(__file__).resolve().parent.parent / "eval" / "audio" / "caso-01-dengue.wav"

RESPOSTA_GEMINI = {
    "turnos": [
        {"falante": "medico", "texto": "bom dia, o que trouxe a senhora aqui?", "inicio": 0.0, "fim": 2.5},
        {"falante": "Paciente", "texto": "estou com febre há três dias.", "inicio": "00:02.5", "fim": "0:06"},
        {"falante": "outro", "texto": "ela quase não come.", "inicio": 6, "fim": 8},
        {"falante": "acompanhante", "texto": "[inaudível]", "inicio": 8, "fim": 9},
        {"falante": "medico", "texto": "   ", "inicio": 9, "fim": 9},
    ]
}


class _ModeloFalso:
    def __init__(self, sdk, **kwargs):
        self.sdk = sdk
        sdk.modelos.append(kwargs)

    def generate_content(self, conteudo, request_options=None):
        self.sdk.chamadas.append({"conteudo": conteudo, "request_options": request_options})
        if self.sdk.erro:
            raise self.sdk.erro
        return types.SimpleNamespace(text=self.sdk.resposta)


def _sdk_falso(resposta=RESPOSTA_GEMINI, erro=None):
    sdk = types.SimpleNamespace(
        modelos=[], chamadas=[], erro=erro,
        resposta=resposta if isinstance(resposta, str) else json.dumps(resposta),
    )
    sdk.GenerativeModel = lambda **kw: _ModeloFalso(sdk, **kw)
    return sdk


def _config(**valores):
    base = {"transcription_provider": "", "gemini_api_key": "", "gemini_audio_model": ""}
    base.update(valores)
    return types.SimpleNamespace(**base)


def _duracao(caminho):
    with wave.open(str(caminho), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


# ---------- escolha do provedor pelo .env ----------

def test_padrao_e_gemini_com_a_chave_do_chat():
    provedor = obter_provedor(_config(gemini_api_key="chave"))
    assert isinstance(provedor, GeminiAudioProvider)
    assert isinstance(provedor, TranscriptionProvider)
    assert provedor.nome == "gemini"
    assert provedor.modelo == gemini_audio.MODELO_PADRAO


def test_gemini_explicito_e_modelo_do_env():
    provedor = obter_provedor(_config(transcription_provider=" Gemini ", gemini_api_key="k",
                                      gemini_audio_model="gemini-x"))
    assert provedor.modelo == "gemini-x"


def test_vosk_mantem_o_diarizador_local():
    assert obter_provedor(_config(transcription_provider="vosk", gemini_api_key="k")) is None


def test_sem_chave_volta_ao_diarizador():
    assert obter_provedor(_config()) is None


def test_provedor_desconhecido_usa_o_padrao():
    assert isinstance(obter_provedor(_config(transcription_provider="xyz", gemini_api_key="k")),
                      GeminiAudioProvider)


# ---------- transcricao da fixture com turnos ----------

def test_transcreve_fixture_com_turnos_e_papeis():
    sdk = _sdk_falso()
    resultado = GeminiAudioProvider(api_key="k", genai_mod=sdk).processar_audio(str(FIXTURE))

    assert set(resultado) == {"full_text", "dialogue", "speakers_count", "duration"}
    papeis = [(t["role"], t["role_key"], t["speaker_id"]) for t in resultado["dialogue"]]
    # turno so com espacos descartado; papel fora da lista vira desconhecido
    assert papeis == [
        ("Médico", "doctor", 0),
        ("Paciente", "patient", 1),
        ("Outro", "other", 2),
        ("Falante não identificado", "unknown", None),
    ]
    assert resultado["speakers_count"] == 4
    assert resultado["dialogue"][0]["text"] == "Bom dia, o que trouxe a senhora aqui?"
    assert resultado["dialogue"][1]["start"] == 2.5
    assert resultado["dialogue"][1]["end"] == 6.0
    assert resultado["full_text"].splitlines()[:2] == [
        "Médico: Bom dia, o que trouxe a senhora aqui?",
        "Paciente: Estou com febre há três dias.",
    ]
    # duracao vem do WAV, nao da estimativa do modelo
    assert resultado["duration"] == pytest.approx(_duracao(FIXTURE))


def test_envia_os_bytes_do_wav_embutidos_com_json():
    sdk = _sdk_falso()
    GeminiAudioProvider(api_key="k", modelo="gemini-x", genai_mod=sdk).processar_audio(str(FIXTURE))

    modelo = sdk.modelos[0]
    assert modelo["model_name"] == "gemini-x"
    assert modelo["generation_config"]["response_mime_type"] == "application/json"
    prompt, audio = sdk.chamadas[0]["conteudo"]
    assert "medico" in prompt and "paciente" in prompt
    assert audio["mime_type"] == "audio/wav"
    assert audio["data"] == FIXTURE.read_bytes()
    assert len(sdk.chamadas) == 1  # abaixo do limite: uma requisicao so


def test_wav_grande_e_fatiado_com_tempos_deslocados(monkeypatch):
    tamanho = FIXTURE.stat().st_size
    monkeypatch.setattr(gemini_audio, "LIMITE_INLINE_BYTES", tamanho // 2)
    sdk = _sdk_falso(resposta={"turnos": [{"falante": "medico", "texto": "oi", "inicio": 1, "fim": 2}]})
    resultado = GeminiAudioProvider(api_key="k", genai_mod=sdk).processar_audio(str(FIXTURE))

    assert len(sdk.chamadas) == 3  # duas metades e o resto do cabecalho
    total = 0.0
    for chamada in sdk.chamadas:
        audio = chamada["conteudo"][1]
        assert len(audio["data"]) <= tamanho // 2
        with wave.open(io.BytesIO(audio["data"]), "rb") as wf:  # cada pedaco e um WAV valido
            total += wf.getnframes() / wf.getframerate()
    assert total == pytest.approx(_duracao(FIXTURE))
    inicios = [t["start"] for t in resultado["dialogue"]]
    assert inicios[0] == 1.0 and inicios[1] > inicios[0] + 10  # segundo pedaco deslocado
    assert resultado["duration"] == pytest.approx(_duracao(FIXTURE))


def test_audio_grande_que_nao_e_wav_falha(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_audio, "LIMITE_INLINE_BYTES", 10)
    mp3 = tmp_path / "consulta.mp3"
    mp3.write_bytes(b"x" * 100)
    with pytest.raises(TranscriptionError, match="limite"):
        GeminiAudioProvider(api_key="k", genai_mod=_sdk_falso()).processar_audio(str(mp3))


def test_erro_do_sdk_nao_vaza_a_chave():
    erro = RuntimeError("400 https://generativelanguage.googleapis.com/x?version=v1beta&key=segredo123 invalid")
    sdk = _sdk_falso(erro=erro)
    with pytest.raises(TranscriptionError) as exc:
        GeminiAudioProvider(api_key="segredo123", genai_mod=sdk).processar_audio(str(FIXTURE))
    assert "segredo123" not in str(exc.value)
    assert "key=<redigida>" in str(exc.value)


def test_resposta_com_cerca_markdown_e_lista_pura():
    sdk = _sdk_falso(resposta='```json\n[{"falante": "médico", "texto": "oi"}]\n```')
    resultado = GeminiAudioProvider(api_key="k", genai_mod=sdk).processar_audio(str(FIXTURE))
    assert resultado["dialogue"][0]["role"] == "Médico"


def test_audio_sem_fala_devolve_contrato_vazio():
    sdk = _sdk_falso(resposta={"turnos": []})
    resultado = GeminiAudioProvider(api_key="k", genai_mod=sdk).processar_audio(str(FIXTURE))
    assert resultado["full_text"] == ""
    assert resultado["dialogue"] == []
    assert resultado["speakers_count"] == 0


@pytest.mark.parametrize("resposta", ["nao e json", '{"outra": 1}'])
def test_resposta_invalida_vira_transcription_error(resposta):
    sdk = _sdk_falso(resposta=resposta)
    with pytest.raises(TranscriptionError):
        GeminiAudioProvider(api_key="k", genai_mod=sdk).processar_audio(str(FIXTURE))


def test_resposta_bloqueada_vira_transcription_error():
    class _Bloqueada:
        @property
        def text(self):
            raise ValueError("finish_reason SAFETY")

    sdk = _sdk_falso()
    sdk.GenerativeModel = lambda **kw: types.SimpleNamespace(
        generate_content=lambda conteudo, request_options=None: _Bloqueada())
    with pytest.raises(TranscriptionError, match="SAFETY"):
        GeminiAudioProvider(api_key="k", genai_mod=sdk).processar_audio(str(FIXTURE))


def test_converter_turnos_tempos_e_papeis():
    turnos = converter_turnos([
        {"falante": "MÉDICO", "texto": "a", "inicio": "01:05", "fim": "00:01:10"},
        {"falante": None, "texto": "b", "inicio": "x", "fim": -3},
        "lixo",
    ])
    assert [(t["role_key"], t["start"], t["end"]) for t in turnos] == [
        ("doctor", 65.0, 70.0),
        ("unknown", 0.0, 0.0),
    ]
    assert turnos[1]["speaker_id"] is None


# ---------- API real (opcional) ----------

@pytest.mark.skipif(not CHAVE_REAL,
                    reason="defina COPMED_GEMINI_REAL=1 e GEMINI_API_KEY para chamar o Gemini")
def test_real_transcreve_fixture_com_turnos():
    provedor = GeminiAudioProvider(api_key=CHAVE_REAL)
    resultado = provedor.processar_audio(str(FIXTURE))
    papeis = {t["role_key"] for t in resultado["dialogue"]}
    assert len(resultado["dialogue"]) >= 2
    assert {"doctor", "patient"} <= papeis
    assert "febre" in resultado["full_text"].lower()
