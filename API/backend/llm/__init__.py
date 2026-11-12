"""Modelo de linguagem do chat e do SOAP (B41, D-06).

`provider.py` define a interface e escolhe o provedor; `claude.py` fala com o
Claude pelo SDK anthropic (padrao) e `gemini.py` com o Gemini pelo google-genai
(reserva); `chat.py` liga o historico da consulta ao provedor para as rotas do
server.py.
"""
from .provider import LlmError, LlmProvider, obter_provedor

__all__ = ["LlmError", "LlmProvider", "obter_provedor"]
