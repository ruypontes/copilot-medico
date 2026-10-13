"""Provedores de transcricao de audio (ADR-04).

O provedor e escolhido por `TRANSCRIPTION_PROVIDER` no .env. Sem a variavel,
a rota /api/transcribe_audio segue com o Diarizador (Vosk + Google).
"""
from .provider import TranscriptionProvider, TranscriptionError, obter_provedor

__all__ = ["TranscriptionProvider", "TranscriptionError", "obter_provedor"]
