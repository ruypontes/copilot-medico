"""Interface comum dos provedores de LLM (B41, ADR-01).

Contrato:

- `enviar_mensagem(consulta_id, historico, texto)`: continua a conversa da
  consulta. `historico` vem do MensagemRepository no formato
  {"role": "user"|"model", "parts": [{"text": ...}]} e pode ja terminar com
  a propria `texto`, que as rotas gravam antes de chamar o modelo.
- `gerar(prompt, instrucao=None, schema=None)`: chamada avulsa, sem historico
  (SOAP, B40). Com `schema`, o modelo responde JSON nesse formato.

Ambos devolvem texto. Falha do provedor (rede, cota, resposta bloqueada)
levanta LlmError.
"""
import threading
from abc import ABC, abstractmethod

from backend.config import settings


class LlmError(Exception):
    """Falha ao chamar o modelo de linguagem."""


class LlmProvider(ABC):
    nome = ""

    @abstractmethod
    def enviar_mensagem(self, consulta_id: str, historico: list[dict], texto: str) -> str:
        ...

    @abstractmethod
    def gerar(self, prompt: str, instrucao: str | None = None, schema: dict | None = None) -> str:
        ...


_provedor: LlmProvider | None = None
_trava = threading.Lock()


def criar_provedor(config=settings) -> LlmProvider | None:
    """Provedor novo a partir da config, ou None sem GEMINI_API_KEY."""
    chave = getattr(config, "gemini_api_key", "")
    if not chave:
        print("⚠️ GEMINI_API_KEY não configurada; o chat responderá com erro.")
        return None
    from .gemini import GeminiProvider

    return GeminiProvider(api_key=chave)


def obter_provedor() -> LlmProvider | None:
    """Provedor unico do processo: cliente e sessoes sao reaproveitados."""
    global _provedor
    with _trava:
        if _provedor is None:
            _provedor = criar_provedor()
        return _provedor
