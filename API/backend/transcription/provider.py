"""Interface comum dos provedores de transcricao (ADR-04).

Contrato: `processar_audio(caminho)` devolve o mesmo dicionario do
Diarizador (backend/audio_service.py), que e o que a rota
/api/transcribe_audio grava e a extensao exibe:

    {
        "full_text": "Falante: texto\\n...",
        "dialogue": [{"role", "role_key", "text", "speaker_id", "start", "end"}],
        "speakers_count": int,
        "duration": float,   # segundos; 0 quando o provedor nao informa
    }

Falha do provedor (rede, cota, resposta invalida) levanta TranscriptionError;
a rota entao cai no Diarizador local e, por fim, na transcricao simples.
"""
from abc import ABC, abstractmethod

from backend.config import settings

PAPEL_NAO_IDENTIFICADO = "Falante não identificado"


class TranscriptionError(Exception):
    """Falha ao transcrever com o provedor externo."""


class TranscriptionProvider(ABC):
    nome = ""

    @abstractmethod
    def processar_audio(self, caminho_audio: str) -> dict:
        ...


def montar_resultado(turnos: list[dict], duracao: float = 0.0) -> dict:
    """Monta o dicionario do contrato a partir de turnos ja preenchidos."""
    dialogo = [t for t in turnos if (t.get("text") or "").strip()]
    ids = {t.get("speaker_id") for t in dialogo}
    return {
        "full_text": "\n".join(f"{t['role']}: {t['text']}" for t in dialogo),
        "dialogue": dialogo,
        "speakers_count": len(ids),
        "duration": float(duracao or 0.0),
    }


def _gemini(config) -> TranscriptionProvider | None:
    chave = getattr(config, "gemini_api_key", "")
    if not chave:
        print("⚠️ Gemini áudio sem GEMINI_API_KEY; usando o Diarizador local.")
        return None
    from .gemini_audio import GeminiAudioProvider

    return GeminiAudioProvider(
        api_key=chave,
        modelo=getattr(config, "gemini_audio_model", "") or None,
    )


def obter_provedor(config=settings) -> TranscriptionProvider | None:
    """Provedor escolhido em TRANSCRIPTION_PROVIDER, ou None para o local.

    Vazio ou "gemini": Gemini audio (padrao do PO, P1). "whisper": Whisper via
    Groq (B32), alternativa para o eval. "vosk": None, que mantem o fluxo
    antigo da rota (Diarizador e transcricao simples).
    """
    nome = (getattr(config, "transcription_provider", "") or "").strip().lower()
    if nome == "vosk":
        return None
    if nome == "whisper":
        chave = getattr(config, "groq_api_key", "")
        if chave:
            from .whisper import WhisperGroqProvider

            return WhisperGroqProvider(
                api_key=chave,
                modelo=getattr(config, "groq_whisper_model", "") or "whisper-large-v3",
            )
        print("⚠️ TRANSCRIPTION_PROVIDER=whisper sem GROQ_API_KEY; usando o provedor padrão.")
    elif nome not in ("", "gemini"):
        print(f"⚠️ TRANSCRIPTION_PROVIDER desconhecido: {nome!r}; usando o provedor padrão.")
    return _gemini(config)
