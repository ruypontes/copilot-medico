"""Claude como provedor padrao do LLM, com o Gemini de reserva.

O Claude nao e chamado de verdade: um cliente falso no lugar do SDK
`anthropic` registra cada pedido. A escolha do provedor usa configs falsas.

Para rodar contra a API real (gasta tokens da chave):
    COPMED_CLAUDE_REAL=1 ANTHROPIC_API_KEY=... pytest tests/test_llm_claude.py -k real
"""
import json
import os
import types

import pytest

from backend.llm import LlmError, provider
from backend.llm.claude import BETA_FALLBACK, ClaudeProvider, _schema_estrito
from backend.llm.gemini import GeminiProvider
from backend.soap.schema import response_schema, validar_soap

# Lida na importacao, antes das fixtures que mexem no ambiente.
CHAVE_REAL = os.environ.get("ANTHROPIC_API_KEY", "") if os.environ.get("COPMED_CLAUDE_REAL") == "1" else ""


class _ErroApi(Exception):
    def __init__(self, status_code, message="erro"):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _resposta(texto="Resposta do Claude.", stop_reason="end_turn", categoria=None):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=texto)] if texto is not None else [],
        stop_reason=stop_reason,
        stop_details=types.SimpleNamespace(category=categoria) if categoria else None,
    )


class _ClienteFalso:
    """Imita client.beta.messages.create; `respostas` sai em ordem (Exception = levanta)."""

    def __init__(self, *respostas):
        self.respostas = list(respostas) or [_resposta()]
        self.pedidos = []
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._criar))

    def _criar(self, **parametros):
        self.pedidos.append(parametros)
        resposta = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def _claude(*respostas, **kwargs):
    cliente = _ClienteFalso(*respostas)
    return ClaudeProvider(api_key="sk-teste", instrucao="Instrução do chat.", cliente=cliente, **kwargs), cliente


def _config(**valores):
    base = {"llm_provider": "", "anthropic_api_key": "", "gemini_api_key": "",
            "claude_model": "", "claude_effort": ""}
    base.update(valores)
    return types.SimpleNamespace(**base)


# ---------- escolha do provedor pelo .env ----------

def test_padrao_e_claude_com_gemini_de_reserva():
    p = provider.criar_provedor(_config(anthropic_api_key="a", gemini_api_key="g"))
    assert isinstance(p, provider.ProvedorComReserva)
    assert [type(x) for x in p.provedores] == [ClaudeProvider, GeminiProvider]
    assert p.nome == "claude+gemini"


def test_so_com_a_chave_do_claude():
    p = provider.criar_provedor(_config(anthropic_api_key="a", claude_model="claude-sonnet-5-5",
                                        claude_effort="low"))
    assert isinstance(p, ClaudeProvider)
    assert (p.modelo, p.esforco) == ("claude-sonnet-5-5", "low")


def test_sem_chave_do_claude_usa_o_gemini():
    assert isinstance(provider.criar_provedor(_config(gemini_api_key="g")), GeminiProvider)


def test_llm_provider_gemini_inverte_a_ordem():
    p = provider.criar_provedor(_config(llm_provider="Gemini", anthropic_api_key="a", gemini_api_key="g"))
    assert [x.nome for x in p.provedores] == ["gemini", "claude"]


def test_provedor_desconhecido_usa_claude():
    p = provider.criar_provedor(_config(llm_provider="xyz", anthropic_api_key="a"))
    assert isinstance(p, ClaudeProvider)


def test_sem_nenhuma_chave():
    assert provider.criar_provedor(_config()) is None


def test_padroes_do_claude():
    p = ClaudeProvider(api_key="a", instrucao="x")
    assert (p.modelo, p.esforco) == ("claude-opus-5-5", "medium")


# ---------- chat ----------

def test_chat_envia_historico_instrucao_e_fallback_de_recusa():
    claude, cliente = _claude()
    historico = [
        {"role": "user", "parts": [{"text": "Paciente com febre."}]},
        {"role": "model", "parts": [{"text": "Há quanto tempo?"}]},
        {"role": "user", "parts": [{"text": "Três dias."}]},  # a rota grava antes de chamar
    ]

    assert claude.enviar_mensagem("c1", historico, "Três dias.") == "Resposta do Claude."

    pedido = cliente.pedidos[0]
    assert pedido["messages"] == [
        {"role": "user", "content": "Paciente com febre."},
        {"role": "assistant", "content": "Há quanto tempo?"},
        {"role": "user", "content": "Três dias."},  # sem duplicar a pergunta atual
    ]
    assert pedido["system"] == "Instrução do chat."
    assert pedido["model"] == "claude-opus-5-5"
    assert pedido["output_config"] == {"effort": "medium"}
    assert pedido["cache_control"] == {"type": "ephemeral"}
    assert pedido["betas"] == [BETA_FALLBACK] and pedido["fallbacks"] == "default"
    assert "thinking" not in pedido  # Opus 5.5: pensamento adaptativo, sempre ligado


def test_chat_que_comeca_pela_ia_e_mensagem_vazia():
    claude, cliente = _claude()
    historico = [
        {"role": "model", "parts": [{"text": "Olá, doutor."}]},
        {"role": "user", "parts": [{"text": "   "}]},
    ]
    claude.enviar_mensagem("c1", historico, "Nova pergunta")
    mensagens = cliente.pedidos[0]["messages"]
    assert mensagens[0]["role"] == "user"  # a API exige começar pelo usuário
    assert [m["content"] for m in mensagens[1:]] == ["Olá, doutor.", "Nova pergunta"]


# ---------- chamada avulsa (SOAP e sugestões) ----------

def test_soap_usa_structured_outputs_com_o_schema_estrito():
    claude, cliente = _claude(_resposta('{"ok": true}'))
    assert claude.gerar("material", instrucao="Gere o SOAP.", schema=response_schema()) == '{"ok": true}'

    pedido = cliente.pedidos[0]
    formato = pedido["output_config"]["format"]
    assert formato["type"] == "json_schema"
    assert formato["schema"]["additionalProperties"] is False
    assert formato["schema"]["properties"]["hipoteses"]["items"]["additionalProperties"] is False
    assert pedido["system"] == "Gere o SOAP." and "cache_control" not in pedido


def test_schema_estrito_nao_altera_o_original():
    original = response_schema()
    _schema_estrito(original)
    assert "additionalProperties" not in original


def test_schema_recusado_repete_pedindo_json_pela_instrucao():
    claude, cliente = _claude(_ErroApi(400, "output_config.format: schema não suportado"), _resposta('{"ok": 1}'))
    assert claude.gerar("material", instrucao="Gere o SOAP.", schema={"type": "object"}) == '{"ok": 1}'
    assert len(cliente.pedidos) == 2
    assert "format" not in cliente.pedidos[1]["output_config"]
    assert "JSON válido" in cliente.pedidos[1]["system"]


def test_sugestoes_pedem_json_pela_instrucao():
    claude, cliente = _claude(_resposta('{"itens": []}'))
    claude.gerar("trecho", instrucao="Sugira itens.", formato_json=True)
    assert cliente.pedidos[0]["system"].startswith("Sugira itens.")
    assert "JSON válido" in cliente.pedidos[0]["system"]
    assert "format" not in cliente.pedidos[0]["output_config"]


# ---------- falhas ----------

def test_cota_esgotada_429():
    claude, _ = _claude(_ErroApi(429, "rate limit"))
    with pytest.raises(LlmError) as erro:
        claude.gerar("x")
    assert erro.value.cota_esgotada is True


def test_outros_erros_viram_llm_error():
    claude, _ = _claude(_ErroApi(401, "invalid x-api-key"))
    with pytest.raises(LlmError) as erro:
        claude.enviar_mensagem("c1", [], "oi")
    assert erro.value.cota_esgotada is False
    assert "sk-teste" not in str(erro.value)


def test_recusa_que_persiste_vira_llm_error_com_a_categoria():
    claude, _ = _claude(_resposta(None, stop_reason="refusal", categoria="bio"))
    with pytest.raises(LlmError, match="bio"):
        claude.gerar("x")


def test_resposta_vazia():
    claude, _ = _claude(_resposta(""))
    with pytest.raises(LlmError, match="vazia"):
        claude.gerar("x")


# ---------- reserva ----------

class _Provedor:
    def __init__(self, nome, erro=None):
        self.nome = nome
        self.erro = erro
        self.chamadas = 0

    def _responder(self):
        self.chamadas += 1
        if self.erro:
            raise self.erro
        return f"resposta do {self.nome}"

    def enviar_mensagem(self, consulta_id, historico, texto):
        return self._responder()

    def gerar(self, prompt, instrucao=None, schema=None, formato_json=False):
        return self._responder()


def test_falha_do_claude_cai_no_gemini(capsys):
    claude, gemini = _Provedor("claude", LlmError("x", cota_esgotada=True)), _Provedor("gemini")
    p = provider.ProvedorComReserva([claude, gemini])
    assert p.gerar("material") == "resposta do gemini"
    assert p.enviar_mensagem("c1", [], "oi") == "resposta do gemini"
    assert "claude: cota esgotada; tentando gemini" in capsys.readouterr().out


def test_principal_ok_nao_chama_a_reserva():
    claude, gemini = _Provedor("claude"), _Provedor("gemini")
    assert provider.ProvedorComReserva([claude, gemini]).gerar("x") == "resposta do claude"
    assert gemini.chamadas == 0


@pytest.mark.parametrize("cotas, esperado", [((True, True), True), ((False, True), False)])
def test_todos_falham(cotas, esperado):
    p = provider.ProvedorComReserva([
        _Provedor("claude", LlmError("c", cota_esgotada=cotas[0])),
        _Provedor("gemini", LlmError("g", cota_esgotada=cotas[1])),
    ])
    with pytest.raises(LlmError) as erro:
        p.gerar("x")
    assert erro.value.cota_esgotada is esperado
    assert "c" in str(erro.value) and "g" in str(erro.value)


# ---------- API real (opcional) ----------

@pytest.mark.skipif(not CHAVE_REAL, reason="defina COPMED_CLAUDE_REAL=1 e ANTHROPIC_API_KEY para chamar o Claude")
def test_real_chat_e_soap():
    claude = ClaudeProvider(api_key=CHAVE_REAL)
    resposta = claude.enviar_mensagem("teste", [], "Responda só: ok")
    assert resposta.strip()
    material = ("## Transcrição da consulta\nMédico: O que a senhora sente?\n"
                "Paciente: Febre há três dias e dor atrás dos olhos.")
    soap = claude.gerar(material, instrucao="Gere o SOAP da consulta em português.", schema=response_schema())
    assert validar_soap(json.loads(soap)).subjetivo
