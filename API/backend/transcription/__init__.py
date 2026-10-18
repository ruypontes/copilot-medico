"""Provedores de transcricao de audio (ADR-04).

O provedor e escolhido por `TRANSCRIPTION_PROVIDER` no .env. Vazio ou
"gemini" usa o Gemini audio (padrao, B31); "whisper" usa o Whisper via Groq
(B32); "vosk" mantem o Diarizador local (Vosk + Google) como fallback offline.
"""
from .provider import TranscriptionProvider, TranscriptionError, obter_provedor

__all__ = ["TranscriptionProvider", "TranscriptionError", "obter_provedor"]
