"""Backend do teste ponta a ponta da extensao (B56).

Sobe o server.py de verdade para o Playwright (front/copmed-extension/e2e):
rotas, login com JWT e cofre (B26), banco com as migracoes, anonimizacao,
audio em partes (B30) e SOAP (B39/B40/B44/B53). So o que depende de IA ou de
modelos locais e trocado:

- IA do chat, do SOAP e das sugestoes: respostas fixas da fixture da consulta.
  O CI nao tem chave do Gemini, e o E2E nao avalia a IA (isso e o eval/).
- Transcricao: o gabarito do audio de fixture, mas so depois de conferir que
  chegou um WAV com som. Se o microfone falso, a gravacao ou o envio das
  partes quebrarem, a transcricao falha e o teste junto.
- Vosk, spaCy e SpeechRecognition: stubs, como no tests/conftest.py. Basta o
  requirements-min.txt.

Cada execucao comeca com um banco SQLite vazio e a medica da fixture aprovada.

    python scripts/servidor_e2e.py --fixture ../front/copmed-extension/e2e/fixtures/consulta-infeccao-respiratoria.json
"""
import argparse
import array
import importlib
import json
import math
import os
import secrets
import shutil
import sys
import tempfile
import types
import wave
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

ADMIN_EMAIL = "admin.e2e@copmed.test"
ADMIN_SENHA = "AdminE2e2026"

# Abaixo disto o WAV e silencio: o microfone falso nao entregou o audio da fixture.
RMS_MINIMO = 100
DURACAO_MINIMA_S = 1.0

# Mesmos papeis do Gemini audio (backend/transcription/gemini_audio.py).
PAPEIS = {
    "medico": ("Médico", "doctor", 0),
    "paciente": ("Paciente", "patient", 1),
}


def configurar_ambiente(pasta: Path) -> None:
    # Variaveis de ambiente vencem o API/.env (pydantic-settings): um .env
    # local com chave do Gemini ou outro banco nao entra no teste.
    os.environ.update({
        "DB_URL": f"sqlite:///{(pasta / 'copmed_e2e.db').as_posix()}",
        "AUTH_SECRET_KEY": secrets.token_urlsafe(48),
        "AUTH_BOOTSTRAP_EMAIL": ADMIN_EMAIL,
        "AUTH_BOOTSTRAP_PASSWORD": ADMIN_SENHA,
        "AUTH_BOOTSTRAP_PROFILES": "administrador",
        "GEMINI_API_KEY": "",
        "TRANSCRIPTION_PROVIDER": "vosk",
        "AUDIO_CHUNKS_DIR": str(pasta / "audio"),
        "AUDIO_CLEANUP_INTERVAL_HOURS": "0",
    })


def ia_da_fixture(fixture: dict, nome: str) -> types.ModuleType:
    """Modulo da IA com as mesmas funcoes que o server.py chama e respostas fixas."""
    mod = types.ModuleType(nome)

    def send_message(patient_id, consultation_id, message_text):
        return fixture["resposta_chat"]

    def gerar_resposta_unica(instrucao, conteudo, response_schema=None):
        # Com response_schema e o SOAP (B40); sem, as sugestoes (B38).
        if response_schema is not None:
            return json.dumps(fixture["soap"], ensure_ascii=False)
        return json.dumps({"itens": []})

    mod.send_message = send_message
    mod.gerar_resposta_unica = gerar_resposta_unica
    return mod


def _stub(nome: str, **atributos) -> types.ModuleType:
    mod = types.ModuleType(nome)
    for chave, valor in atributos.items():
        setattr(mod, chave, valor)
    return mod


class _SemTranscricaoSimples:
    """No lugar do Transcritor Simples (Google): no E2E so vale a fixture."""

    def __init__(self, *args, **kwargs):
        self.reconhecedor = self

    def record(self, source):
        raise RuntimeError("E2E: a transcricao da fixture recusou o audio")


class _SemDiarizador:
    """No lugar do Diarizador (Vosk): no E2E so vale a fixture."""

    def __init__(self, *args, **kwargs):
        pass

    def processar_audio(self, caminho_audio):
        raise RuntimeError("E2E: a transcricao da fixture recusou o audio")


class _AudioFileVazio:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def instalar_stubs(fixture: dict) -> None:
    """Troca os modulos pesados antes do `import server` (ver tests/conftest.py)."""
    importlib.import_module("backend")
    voz = _stub("backend.processador_voz", __path__=[])
    voz_sub = _stub("backend.processador_voz.processador_voz", TranscritorVoz=_SemTranscricaoSimples)
    voz.processador_voz = voz_sub
    stubs = {
        "speech_recognition": _stub(
            "speech_recognition",
            AudioFile=_AudioFileVazio,
            Recognizer=_SemTranscricaoSimples,
            UnknownValueError=type("UnknownValueError", (Exception,), {}),
            RequestError=type("RequestError", (Exception,), {}),
        ),
        "backend.audio_service": _stub("backend.audio_service", Diarizador=_SemDiarizador),
        "backend.processador_voz": voz,
        "backend.processador_voz.processador_voz": voz_sub,
        "backend.text_filter": _stub(
            "backend.text_filter", remover_nomes=lambda texto: texto, retornar_nome=lambda texto: ""
        ),
        "backend.pdf_reader": _stub("backend.pdf_reader", extract_text_from_pdf=lambda arquivo: ""),
        "backend.gemini_connection": ia_da_fixture(fixture, "backend.gemini_connection"),
    }
    # Com o B41 a IA passa de backend/gemini_connection.py para backend/llm/chat.py.
    try:
        importlib.import_module("backend.llm")
        stubs["backend.llm.chat"] = ia_da_fixture(fixture, "backend.llm.chat")
    except ModuleNotFoundError:
        pass
    sys.modules.update(stubs)


def medir_wav(caminho: str) -> tuple[float, float]:
    """(duracao em segundos, RMS) de um WAV PCM de 16 bits."""
    with wave.open(caminho, "rb") as wav:
        if wav.getsampwidth() != 2:
            raise ValueError(f"WAV de {wav.getsampwidth() * 8} bits; esperado 16")
        quadros = wav.readframes(wav.getnframes())
        duracao = wav.getnframes() / wav.getframerate()
    amostras = array.array("h", quadros)
    if sys.byteorder == "big":
        amostras.byteswap()
    if not amostras:
        return duracao, 0.0
    return duracao, math.sqrt(sum(a * a for a in amostras) / len(amostras))


def criar_provedor(fixture: dict):
    from backend.transcription.provider import (
        TranscriptionError,
        TranscriptionProvider,
        montar_resultado,
    )

    class TranscricaoDaFixture(TranscriptionProvider):
        nome = "fixture-e2e"

        def processar_audio(self, caminho_audio: str) -> dict:
            duracao, rms = medir_wav(caminho_audio)
            print(f"[E2E] Parte de audio recebida: {duracao:.1f}s, RMS {rms:.0f}.")
            if duracao < DURACAO_MINIMA_S or rms < RMS_MINIMO:
                raise TranscriptionError(
                    f"audio sem som ou curto demais ({duracao:.1f}s, RMS {rms:.0f})"
                )
            turnos = []
            passo = duracao / len(fixture["transcricao"])
            for i, fala in enumerate(fixture["transcricao"]):
                role, role_key, speaker_id = PAPEIS[fala["papel"]]
                turnos.append({
                    "role": role,
                    "role_key": role_key,
                    "text": fala["texto"],
                    "speaker_id": speaker_id,
                    "start": round(i * passo, 2),
                    "end": round((i + 1) * passo, 2),
                })
            return montar_resultado(turnos, duracao)

    return TranscricaoDaFixture()


def preparar_banco(fixture: dict) -> None:
    """Migracoes e a medica da fixture, cadastrada e aprovada pelo administrador."""
    from backend import auth_service
    from repositories import sessao

    sessao.aplicar_migracoes()
    auth_service.bootstrap_users_if_needed()
    admin = auth_service.find_user_by_email(ADMIN_EMAIL)
    medica = fixture["medico"]
    pedido = auth_service.create_doctor_registration(
        name=medica["nome"], email=medica["email"], password=medica["senha"], crm="E2E-0001"
    )
    auth_service.approve_doctor_request(pedido["id"], admin["id"])
    sessao.encerrar_sessao()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", type=Path, required=True, help="JSON da consulta do E2E")
    parser.add_argument("--porta", type=int, default=3001)
    args = parser.parse_args(argv)

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    # Sempre a mesma pasta, zerada a cada execucao: o banco comeca vazio e nada acumula.
    pasta = Path(tempfile.gettempdir()) / "copmed-e2e"
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir()
    configurar_ambiente(pasta)
    instalar_stubs(fixture)
    preparar_banco(fixture)

    server = importlib.import_module("server")
    server.transcription_provider = criar_provedor(fixture)
    print(f"[E2E] Backend do E2E em http://localhost:{args.porta} (dados em {pasta}).")
    server.app.run(host="127.0.0.1", port=args.porta, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
