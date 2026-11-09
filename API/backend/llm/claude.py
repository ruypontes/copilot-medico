"""Claude (Anthropic) como provedor padrao do chat, do SOAP e das sugestoes.

Mesmo contrato do GeminiProvider (provider.py). O historico da consulta vem
do banco a cada mensagem e vai inteiro para a API, que nao guarda estado; o
cache de prompt (cache_control) evita pagar de novo pelo prefixo repetido.

- Recusa de seguranca (stop_reason "refusal"): nos modelos que aceitam, o
  proprio servidor da Anthropic refaz o pedido em outro modelo Claude
  (fallbacks "default"); o Haiku 5.5 nao tem esse recurso. Se a recusa ficar,
  vira LlmError e o provedor de reserva (Gemini) tenta.
- Saida em JSON com schema (SOAP do B40): structured outputs. O schema do
  SoapV1 foi escrito no subconjunto do Gemini; aqui os objetos ganham
  `additionalProperties: false`, que a API exige. Se ainda assim a API
  recusar o schema, repete pedindo o JSON so pela instrucao - o SOAP e
  validado pelo SoapV1 de qualquer jeito.

O SDK so e importado na primeira chamada, para o servidor e os testes subirem
sem ele.
"""
import threading

from .gemini import INSTRUCAO_CHAT, _conversa
from .provider import LlmError, LlmProvider

# Haiku 5.5: rapido e barato para o volume do chat; esforco alto compensa
# no SOAP. Os dois mudam pelo .env (CLAUDE_MODEL, CLAUDE_EFFORT).
MODELO_PADRAO = "claude-haiku-5-5"
ESFORCO_PADRAO = "high"
# Cobre o pensamento adaptativo (ligado por padrao) mais a resposta.
MAX_TOKENS = 16000
BETA_FALLBACK = "server-side-fallback-2026-07-01"
# So estes modelos aceitam o fallback de recusa no servidor.
MODELOS_COM_FALLBACK = frozenset({
    "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5-2",
})

# O banco grava as mensagens no formato do Gemini ("model"); a API usa "assistant".
PAPEIS = {"user": "user", "model": "assistant", "assistant": "assistant"}
INSTRUCAO_JSON = (
    "\n\nResponda somente com um objeto JSON válido, sem texto antes ou depois "
    "e sem cercas de código."
)
INICIO_DA_CONVERSA = "(Início do histórico da consulta.)"


class _PedidoInvalido(LlmError):
    """HTTP 400: parametro que a API nao aceitou (ex.: schema do JSON)."""


def _schema_estrito(no):
    """Copia do schema com `additionalProperties: false` em todo objeto."""
    if isinstance(no, list):
        return [_schema_estrito(item) for item in no]
    if not isinstance(no, dict):
        return no
    copia = {chave: _schema_estrito(valor) for chave, valor in no.items()}
    if copia.get("type") == "object" or "properties" in copia:
        copia.setdefault("additionalProperties", False)
    return copia


def _falha(erro: Exception) -> LlmError:
    """Erro do SDK -> LlmError, sem depender das classes do SDK (testes)."""
    status = getattr(erro, "status_code", None)
    mensagem = f"Falha ao chamar o Claude: {type(erro).__name__}"
    if getattr(erro, "message", None):
        mensagem += f": {erro.message}"
    if status == 400:
        return _PedidoInvalido(mensagem)
    return LlmError(mensagem, cota_esgotada=status == 429 or type(erro).__name__ == "RateLimitError")


class ClaudeProvider(LlmProvider):
    nome = "claude"

    def __init__(self, api_key: str, modelo: str | None = None, esforco: str | None = None,
                 instrucao: str | None = None, timeout: float = 120.0, cliente=None):
        self.api_key = api_key
        self.modelo = modelo or MODELO_PADRAO
        self.esforco = esforco or ESFORCO_PADRAO
        if instrucao is None:
            instrucao = INSTRUCAO_CHAT.read_text(encoding="utf-8")
        self.instrucao = instrucao
        self.timeout = timeout
        self._cliente = cliente  # testes injetam um cliente falso
        self._trava = threading.Lock()

    def _client(self):
        with self._trava:
            if self._cliente is None:
                try:
                    import anthropic
                except ImportError as e:
                    raise LlmError("Pacote anthropic não instalado") from e
                # O SDK ja repete 429/5xx e erros de conexao (max_retries)
                self._cliente = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)
            return self._cliente

    def _criar(self, mensagens: list[dict], sistema: str | None = None,
               formato: dict | None = None, cache: bool = False) -> str:
        output_config = {"effort": self.esforco}
        if formato is not None:
            output_config["format"] = formato
        parametros = {
            "model": self.modelo,
            "max_tokens": MAX_TOKENS,
            "messages": mensagens,
            "output_config": output_config,
        }
        if self.modelo in MODELOS_COM_FALLBACK:
            parametros["betas"] = [BETA_FALLBACK]
            parametros["fallbacks"] = "default"
        if sistema:
            parametros["system"] = sistema
        if cache:
            parametros["cache_control"] = {"type": "ephemeral"}
        try:
            resposta = self._client().beta.messages.create(**parametros)
        except LlmError:
            raise
        except Exception as e:
            raise _falha(e) from e

        if resposta.stop_reason == "refusal":
            # Categoria ajuda a investigar; nunca o conteudo da consulta.
            detalhes = getattr(resposta, "stop_details", None)
            categoria = getattr(detalhes, "category", None) if detalhes else None
            raise LlmError(f"Claude recusou o pedido (categoria: {categoria or 'não informada'})")
        texto = "".join(bloco.text for bloco in resposta.content if bloco.type == "text")
        if not texto.strip():
            raise LlmError(f"Claude devolveu uma resposta vazia (stop_reason: {resposta.stop_reason})")
        return texto

    def enviar_mensagem(self, consulta_id: str, historico: list[dict], texto: str) -> str:
        mensagens = [
            {"role": PAPEIS.get(role, "user"), "content": conteudo}
            for role, conteudo in _conversa(historico, texto)
            if conteudo.strip()  # a API recusa bloco de texto vazio
        ]
        mensagens.append({"role": "user", "content": texto})
        if mensagens[0]["role"] != "user":
            # A conversa precisa comecar pelo usuario
            mensagens.insert(0, {"role": "user", "content": INICIO_DA_CONVERSA})
        return self._criar(mensagens, sistema=self.instrucao, cache=True)

    def gerar(self, prompt: str, instrucao: str | None = None, schema: dict | None = None,
              formato_json: bool = False) -> str:
        mensagens = [{"role": "user", "content": prompt}]
        if schema is not None:
            formato = {"type": "json_schema", "schema": _schema_estrito(schema)}
            try:
                return self._criar(mensagens, sistema=instrucao, formato=formato)
            except _PedidoInvalido as e:
                print(f"[LLM] Claude recusou o schema do JSON; repetindo só com a instrução ({e}).")
        if formato_json or schema is not None:
            instrucao = (instrucao or "") + INSTRUCAO_JSON
        return self._criar(mensagens, sistema=instrucao)
