
def _segment(text, start, end, spk=None):
    segment = {
        "text": text,
        "result": [
            {"start": start, "end": end, "word": text}
        ],
    }
    if spk is not None:
        segment["spk"] = spk
    return segment


def test_mesclar_segmentos_sem_vetor(real_module):
    mod = real_module("backend.audio_service")
    diarizador = mod.Diarizador.__new__(mod.Diarizador)

    resultado = diarizador._mesclar_e_classificar([
        _segment("bom dia", 0.0, 1.0),
        _segment("como vai", 1.5, 2.0),
    ])

    assert len(resultado) == 1
    assert resultado[0]["text_combined"] == "bom dia como vai"
    assert resultado[0]["speaker_id"] is None
    assert resultado[0]["role_key"] == "unknown"


def test_nao_mesclar_segmentos_com_silencio_longo(real_module):
    mod = real_module("backend.audio_service")
    diarizador = mod.Diarizador.__new__(mod.Diarizador)

    resultado = diarizador._mesclar_e_classificar([
        _segment("primeiro", 0.0, 1.0),
        _segment("segundo", 3.0, 4.0),
    ])

    assert len(resultado) == 2


def test_identificar_mesma_voz_por_vetor(real_module):
    mod = real_module("backend.audio_service")
    diarizador = mod.Diarizador.__new__(mod.Diarizador)

    resultado = diarizador._mesclar_e_classificar([
        _segment("ola", 0.0, 1.0, [0.1, 0.2, 0.3]),
        _segment("tudo bem", 3.0, 4.0, [0.15, 0.2, 0.3]),
    ])

    assert len(resultado) == 2
    assert resultado[0]["speaker_id"] == resultado[1]["speaker_id"]
    assert resultado[0]["role_key"] == "unknown"


def test_identificar_falantes_com_vetores_diferentes(real_module):
    mod = real_module("backend.audio_service")
    diarizador = mod.Diarizador.__new__(mod.Diarizador)

    resultado = diarizador._mesclar_e_classificar([
        _segment("ola", 0.0, 1.0, [0.1, 0.2, 0.3]),
        _segment("bom dia", 1.2, 2.0, [3.0, 4.0, 5.0]),
    ])

    assert len(resultado) == 2
    assert resultado[0]["speaker_id"] != resultado[1]["speaker_id"]


def test_ignorar_segmentos_invalidos(real_module):
    mod = real_module("backend.audio_service")
    diarizador = mod.Diarizador.__new__(mod.Diarizador)

    resultado = diarizador._mesclar_e_classificar([
        {"text": "sem palavras", "result": []},
        _segment("tempo invertido", 3.0, 1.0),
        {
            "text": "sem timestamp",
            "result": [{"word": "teste"}],
        },
        _segment("segmento valido", 4.0, 5.0),
    ])

    assert len(resultado) == 1
    assert resultado[0]["text_combined"] == "segmento valido"


def test_vetor_invalido_nao_impede_transcricao(real_module):
    mod = real_module("backend.audio_service")
    diarizador = mod.Diarizador.__new__(mod.Diarizador)

    resultado = diarizador._mesclar_e_classificar([
        _segment("texto preservado", 0.0, 1.0, [float("nan"), 0.2]),
    ])

    assert len(resultado) == 1
    assert resultado[0]["text_combined"] == "texto preservado"
    assert resultado[0]["speaker_id"] is None
    assert resultado[0]["role_key"] == "unknown"


def test_processar_audio_wav_invalido(real_module, tmp_path):
    mod = real_module("backend.audio_service")
    diarizador = mod.Diarizador.__new__(mod.Diarizador)

    arquivo = tmp_path / "invalido.wav"
    arquivo.write_bytes(b"isso nao e um arquivo wav")

    import pytest

    with pytest.raises(ValueError, match="Arquivo WAV inválido"):
        diarizador.processar_audio(str(arquivo))


def test_processar_audio_usa_fallback_vosk(real_module, tmp_path, monkeypatch):
    import json
    import wave
    import sys
    import types

    mod = real_module("backend.audio_service")

    # Simula AudioData, ausente no stub global.
    fake_sr = types.ModuleType("speech_recognition")

    class AudioData:
        def __init__(self, frame_data, sample_rate, sample_width):
            self.frame_data = frame_data
            self.sample_rate = sample_rate
            self.sample_width = sample_width

    fake_sr.AudioData = AudioData
    monkeypatch.setitem(sys.modules, "speech_recognition", fake_sr)
    monkeypatch.setattr(mod, "sr", fake_sr)

    # Simula Vosk: um segmento com texto e timestamps.
    class FakeRecognizer:
        def __init__(self, *args):
            self.processado = False

        def SetWords(self, value):
            pass

        def AcceptWaveform(self, data):
            if not self.processado:
                self.processado = True
                return True
            return False

        def Result(self):
            return json.dumps({
                "text": "texto do vosk",
                "result": [
                    {"start": 0.0, "end": 1.0, "word": "texto"},
                    {"start": 1.0, "end": 1.5, "word": "vosk"},
                ],
            })

        def FinalResult(self):
            return json.dumps({})

    monkeypatch.setattr(mod, "KaldiRecognizer", FakeRecognizer)

    # Garante que o Google falhe e o Vosk seja utilizado.
    class FakeTranscritor:
        def transcrever(self, audio):
            return None

    diarizador = mod.Diarizador.__new__(mod.Diarizador)
    diarizador.model = object()
    diarizador.spk_model = object()
    diarizador.transcritor_google = FakeTranscritor()

    # WAV mono, 16 kHz, com duração suficiente para gerar um bloco.
    arquivo = tmp_path / "audio.wav"
    with wave.open(str(arquivo), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x01\x00" * 32000)

    resultado = diarizador.processar_audio(str(arquivo))

    assert "texto do vosk" in resultado["full_text"].lower()
    assert len(resultado["dialogue"]) == 1
    assert resultado["used_fallback"] is True
