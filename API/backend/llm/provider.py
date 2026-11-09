"""Interface comum dos provedores de LLM (B41, ADR-01).

Claude (claude.py) e o provedor padrao e o Gemini (gemini.py) a reserva;
LLM_PROVIDER no .env troca a ordem.

Contrato:

- `enviar_mensagem(consulta_id, historico, texto)`: continua a conversa da
  consulta. `historico` vem do MensagemRepository no formato
  {"role": "user"|"model", "parts": [{"text": ...}]} e pode ja terminar com
  a propria `texto`, que as rotas gravam antes de chamar o modelo.
- `gerar(prompt, instrucao=None, schema=None, formato_json=False)`: chamada
  avulsa, sem historico (recomendacoes do B38, SOAP do B40). Com
  `formato_json` o modelo responde JSON; com `schema`, JSON nesse formato.

Ambos devolvem texto. Falha do provedor (rede, cota, resposta bloqueada)
levanta LlmError; cota esgotada vem com `cota_esgotada=True`.
"""
import threading
from abc import ABC, abstractmethod

from backend.config import settings


class LlmError(Exception):
    """Falha ao chamar o modelo de linguagem.

    `cota_esgotada` marca o limite de uso do provedor (HTTP 429): a rota do
    SOAP responde 429 e o avaliar_soap espera antes de tentar de novo.
    """

    def __init__(self, mensagem: str = "", cota_esgotada: bool = False):
        super().__init__(mensagem)
        self.cota_esgotada = cota_esgotada


class LlmProvider(ABC):
    nome = ""

    @abstractmethod
    def enviar_mensagem(self, consulta_id: str, historico: list[dict], texto: str) -> str:
        ...

    @abstractmethod
    def gerar(self, prompt: str, instrucao: str | None = None, schema: dict | None = None,
              formato_json: bool = False) -> str:
        ...


_provedor: LlmProvider | None = None
_trava = threading.Lock()

# Ordem padrao: Claude e o principal; o Gemini fica de reserva.
PROVEDORES = ("claude", "gemini")


class ProvedorComReserva(LlmProvider):
    """Tenta os provedores em ordem: se o principal falhar (cota, rede,
    recusa), o proximo responde. So o nome do provedor e o tipo da falha vao
    para o log, nunca o conteudo da consulta."""

    def __init__(self, provedores: list[LlmProvider]):
        self.provedores = provedores
        self.nome = "+".join(p.nome for p in provedores)

    def _em_ordem(self, chamar):
        erros = []
        for indice, provedor in enumerate(self.provedores):
            try:
                return chamar(provedor)
            except LlmError as e:
                erros.append(e)
                proximo = self.provedores[indice + 1].nome if indice + 1 < len(self.provedores) else None
                if proximo:
                    motivo = "cota esgotada" if e.cota_esgotada else "falha"
                    print(f"[LLM] {provedor.nome}: {motivo}; tentando {proximo}.")
        raise LlmError(
            " | ".join(str(e) for e in erros),
            cota_esgotada=all(e.cota_esgotada for e in erros),
        ) from erros[-1]

    def enviar_mensagem(self, consulta_id: str, historico: list[dict], texto: str) -> str:
        return self._em_ordem(lambda p: p.enviar_mensagem(consulta_id, historico, texto))

    def gerar(self, prompt: str, instrucao: str | None = None, schema: dict | None = None,
              formato_json: bool = False) -> str:
        return self._em_ordem(lambda p: p.gerar(prompt, instrucao, schema, formato_json))


def _criar_um(nome: str, config) -> LlmProvider | None:
    """Um provedor pelo nome, ou None se a chave dele nao estiver no .env."""
    if nome == "claude":
        chave = getattr(config, "anthropic_api_key", "")
        if not chave:
            return None
        from .claude import ClaudeProvider

        return ClaudeProvider(
            api_key=chave,
            modelo=getattr(config, "claude_model", "") or None,
            esforco=getattr(config, "claude_effort", "") or None,
        )
    chave = getattr(config, "gemini_api_key", "")
    if not chave:
        return None
    from .gemini import GeminiProvider

    return GeminiProvider(api_key=chave)


def criar_provedor(config=settings) -> LlmProvider | None:
    """Provedor a partir da config: LLM_PROVIDER escolhe o principal (padrao
    "claude") e os demais com chave configurada viram reserva, na ordem de
    PROVEDORES. None se nenhum provedor tiver chave."""
    principal = (getattr(config, "llm_provider", "") or "claude").strip().lower()
    if principal not in PROVEDORES:
        print(f"⚠️ LLM_PROVIDER desconhecido: {principal!r}; usando claude.")
        principal = "claude"
    ordem = [principal] + [nome for nome in PROVEDORES if nome != principal]
    provedores = [p for p in (_criar_um(nome, config) for nome in ordem) if p is not None]
    if not provedores:
        print("⚠️ Nenhuma chave de IA configurada (ANTHROPIC_API_KEY ou GEMINI_API_KEY); "
              "o chat responderá com erro.")
        return None
    if provedores[0].nome != principal:
        print(f"⚠️ Sem chave para {principal}; usando {provedores[0].nome}.")
    return provedores[0] if len(provedores) == 1 else ProvedorComReserva(provedores)


def obter_provedor() -> LlmProvider | None:
    """Provedor unico do processo: cliente e sessoes sao reaproveitados."""
    global _provedor
    with _trava:
        if _provedor is None:
            _provedor = criar_provedor()
        return _provedor
