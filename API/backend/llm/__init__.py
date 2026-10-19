"""Modelo de linguagem do chat e do SOAP (B41, D-06).

`provider.py` define a interface e escolhe o provedor; `gemini.py` fala com o
Gemini pelo SDK google-genai; `chat.py` liga o historico da consulta ao
provedor para as rotas do server.py.
"""
from .provider import LlmError, LlmProvider, obter_provedor

__all__ = ["LlmError", "LlmProvider", "obter_provedor"]
