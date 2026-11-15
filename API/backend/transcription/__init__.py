"""Provedores de transcricao de audio (ADR-04).

O provedor e escolhido por `TRANSCRIPTION_PROVIDER` no .env. Vazio ou
"whisper" usa o Whisper via Groq (padrao, B32), com o Gemini audio (B31) de
reserva quando falta a GROQ_API_KEY; "gemini" forca o Gemini audio; "vosk"
mantem o Diarizador local (Vosk + Google) como fallback offline.
"""
from .provider import TranscriptionProvider, TranscriptionError, obter_provedor

__all__ = ["TranscriptionProvider", "TranscriptionError", "obter_provedor"]
