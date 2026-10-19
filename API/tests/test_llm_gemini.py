"""B41: provedor de LLM com google-genai e sessao reaproveitada.

O Gemini nao e chamado de verdade: o SDK `google-genai` e trocado por um
falso injetado no provedor, que registra cada cliente, sessao e mensagem.

Para rodar contra a API real (gasta cota da chave):
    COPMED_GEMINI_REAL=1 GEMINI_API_KEY=... pytest tests/test_llm_gemini.py -k real
"""
import importlib.util
import os
import pathlib
import types

import pytest

from backend.llm import LlmError, LlmProvider
from backend.llm import gemini, provider
from backend.llm.gemini import GeminiProvider

# Lida na importacao: a fixture env_for_config troca GEMINI_API_KEY por um falso.
CHAVE_REAL = os.environ.get("GEMINI_API_KEY", "") if os.environ.get("COPMED_GEMINI_REAL") == "1" else ""

API_DIR = pathlib.Path(__file__).resolve().parent.parent


class _ChatFalso:
    def __init__(self, sdk, model, config, history):
        self.sdk = sdk
        self.model = model
        self.config = config
        self.history = history
        self.enviadas = []

    def send_message(self, message):
        self.enviadas.append(message)
        if self.sdk.erro:
            raise self.sdk.erro
        self.sdk.respondidas += 1
        texto = self.sdk.resposta if self.sdk.resposta != "auto" else f"resposta {self.sdk.respondidas}"
        return types.SimpleNamespace(text=texto)


class _ClienteFalso:
    def __init__(self, sdk, **kwargs):
        self.sdk = sdk
        sdk.clientes.append(kwargs)
        self.chats = types.SimpleNamespace(create=self._criar_chat)
        self.models = types.SimpleNamespace(generate_content=self._gerar)

    def _criar_chat(self, model, config=None, history=None):
        chat = _ChatFalso(self.sdk, model, config, history)
        self.sdk.sessoes.append(chat)
        return chat

    def _gerar(self, model, contents, config=None):
        self.sdk.geracoes.append({"model": model, "contents": contents, "config": config})
        if self.sdk.erro:
            raise self.sdk.erro
        return types.SimpleNamespace(text='{"ok": true}')


def _sdk_falso(resposta="auto", erro=None):
    sdk = types.SimpleNamespace(
        clientes=[], sessoes=[], geracoes=[], respondidas=0, resposta=resposta, erro=erro,
    )
    sdk.Client = lambda **kw: _ClienteFalso(sdk, **kw)
    return sdk


def _msg(role, texto):
    return {"role": role, "parts": [{"text": texto}], "timestamp": "2026-10-19T12:00:00+00:00"}


def _provedor(sdk, **kwargs):
    return GeminiProvider(api_key="k", instrucao="instrucao do sistema", genai_mod=sdk, **kwargs)


# ---------- escolha do provedor ----------

def test_sem_chave_nao_ha_provedor():
    assert provider.criar_provedor(types.SimpleNamespace(gemini_api_key="")) is None


def test_com_chave_usa_gemini_com_a_instrucao_do_chat():
    provedor = provider.criar_provedor(types.SimpleNamespace(gemini_api_key="chave"))
    assert isinstance(provedor, GeminiProvider)
    assert isinstance(provedor, LlmProvider)
    assert provedor.nome == "gemini"
    assert provedor.modelo == gemini.MODELO_PADRAO
    assert provedor.instrucao == gemini.INSTRUCAO_CHAT.read_text(encoding="utf-8")
    assert provedor.instrucao.strip()


# ---------- chat com sessao reaproveitada ----------

def test_primeira_mensagem_cria_sessao_com_historico_do_banco():
    sdk = _sdk_falso()
    historico = [_msg("user", "oi"), _msg("model", "ola"), _msg("user", "febre ha 3 dias")]

    resposta = _provedor(sdk).enviar_mensagem("c1", historico, "febre ha 3 dias")

    assert resposta == "resposta 1"
    assert sdk.clientes == [{"api_key": "k", "http_options": {"timeout": 120_000}}]
    chat = sdk.sessoes[0]
    assert chat.model == gemini.MODELO_PADRAO
    assert chat.config["system_instruction"] == "instrucao do sistema"
    assert {s["threshold"] for s in chat.config["safety_settings"]} == {"BLOCK_MEDIUM_AND_ABOVE"}
    # a pergunta atual, ja gravada pela rota, nao vai duas vezes
    assert chat.history == [
        {"role": "user", "parts": [{"text": "oi"}]},
        {"role": "model", "parts": [{"text": "ola"}]},
    ]
    assert chat.enviadas == ["febre ha 3 dias"]


def test_mensagem_seguinte_reaproveita_a_sessao():
    sdk = _sdk_falso()
    provedor = _provedor(sdk)
    historico = [_msg("user", "primeira")]
    resposta = provedor.enviar_mensagem("c1", historico, "primeira")
    # a rota grava a resposta e a nova pergunta antes de chamar de novo
    historico += [_msg("model", resposta), _msg("user", "segunda")]

    assert provedor.enviar_mensagem("c1", historico, "segunda") == "resposta 2"
    assert len(sdk.sessoes) == 1
    assert sdk.sessoes[0].enviadas == ["primeira", "segunda"]
    assert len(sdk.clientes) == 1


def test_historico_diferente_do_banco_recria_a_sessao():
    sdk = _sdk_falso()
    provedor = _provedor(sdk)
    provedor.enviar_mensagem("c1", [], "recomendacoes?")  # rota que nao grava no banco

    historico = [_msg("user", "pergunta nova")]
    provedor.enviar_mensagem("c1", historico, "pergunta nova")

    assert len(sdk.sessoes) == 2
    assert sdk.sessoes[1].history == []  # o banco manda; a recomendacao nao entra


def test_consultas_diferentes_tem_sessoes_separadas_e_um_cliente():
    sdk = _sdk_falso()
    provedor = _provedor(sdk)
    provedor.enviar_mensagem("c1", [], "a")
    provedor.enviar_mensagem("c2", [], "b")
    assert [s.enviadas for s in sdk.sessoes] == [["a"], ["b"]]
    assert len(sdk.clientes) == 1


def test_sessoes_antigas_saem_do_cache():
    sdk = _sdk_falso()
    provedor = _provedor(sdk, max_sessoes=2)
    for consulta in ("c1", "c2", "c3"):
        provedor.enviar_mensagem(consulta, [], "oi")
    assert list(provedor._sessoes) == ["c2", "c3"]


def test_mensagem_mal_formatada_e_ignorada():
    sdk = _sdk_falso()
    _provedor(sdk).enviar_mensagem("c1", [{"texto": "sem role"}, _msg("user", "ok")], "nova")
    assert sdk.sessoes[0].history == [{"role": "user", "parts": [{"text": "ok"}]}]


def test_erro_do_sdk_vira_llm_error_sem_a_chave_e_descarta_a_sessao():
    sdk = _sdk_falso(erro=RuntimeError("400 https://x/v1beta/models?key=segredo123 invalid segredo123"))
    provedor = GeminiProvider(api_key="segredo123", instrucao="x", genai_mod=sdk)
    with pytest.raises(LlmError) as exc:
        provedor.enviar_mensagem("c1", [], "oi")
    assert "segredo123" not in str(exc.value)
    assert "key=<redigida>" in str(exc.value)
    assert "c1" not in provedor._sessoes

    sdk.erro = None
    provedor.enviar_mensagem("c1", [], "oi")
    assert len(sdk.sessoes) == 2


def test_resposta_bloqueada_vira_llm_error():
    # google-genai devolve text=None em vez de levantar quando bloqueia
    sdk = _sdk_falso(resposta=None)
    with pytest.raises(LlmError, match="vazia ou bloqueada"):
        _provedor(sdk).enviar_mensagem("c1", [], "oi")


# ---------- geracao avulsa (SOAP) ----------

def test_gerar_com_schema_pede_json_sem_historico():
    sdk = _sdk_falso()
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    texto = _provedor(sdk, modelo="gemini-x").gerar("monte o SOAP", instrucao="voce e medico", schema=schema)

    assert texto == '{"ok": true}'
    chamada = sdk.geracoes[0]
    assert chamada["model"] == "gemini-x"
    assert chamada["contents"] == "monte o SOAP"
    assert chamada["config"]["response_mime_type"] == "application/json"
    assert chamada["config"]["response_schema"] == schema
    assert chamada["config"]["system_instruction"] == "voce e medico"
    assert sdk.sessoes == []


def test_gerar_sem_schema_nem_instrucao():
    sdk = _sdk_falso()
    _provedor(sdk).gerar("resuma")
    assert set(sdk.geracoes[0]["config"]) == {"safety_settings"}


# ---------- send_message usado pelas rotas ----------

def _chat_real():
    """backend/llm/chat.py de verdade; o conftest troca o modulo por um stub."""
    spec = importlib.util.spec_from_file_location(
        "backend.llm.chat_real_b41", API_DIR / "backend" / "llm" / "chat.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_send_message_le_o_historico_e_chama_o_provedor(monkeypatch):
    chat = _chat_real()
    chamadas = []

    class _Provedor:
        def enviar_mensagem(self, consulta_id, historico, texto):
            chamadas.append((consulta_id, historico, texto))
            return "resposta da IA"

    class _Repo:
        def __init__(self, sessao):
            pass

        def historico(self, consulta_id):
            return [_msg("user", "oi")]

    monkeypatch.setattr(chat, "obter_provedor", lambda: _Provedor())
    monkeypatch.setattr(chat, "MensagemRepository", _Repo)
    monkeypatch.setattr(chat, "sessao", types.SimpleNamespace(obter_sessao=lambda: None))

    assert chat.send_message("p1", "c1", "oi") == "resposta da IA"
    assert chamadas == [("c1", [_msg("user", "oi")], "oi")]


def test_send_message_sem_chave_responde_com_erro(monkeypatch):
    chat = _chat_real()
    monkeypatch.setattr(chat, "obter_provedor", lambda: None)
    resposta = chat.send_message("p1", "c1", "oi")
    assert resposta.startswith("Desculpe, ocorreu um erro")
    assert "GEMINI_API_KEY" in resposta


# ---------- SDK antigo removido ----------

def test_sdk_antigo_nao_e_mais_usado():
    requisitos = (API_DIR / "requirements.txt").read_text(encoding="utf-8")
    assert "google-generativeai" not in requisitos
    assert "google-genai" in requisitos
    assert not (API_DIR / "backend" / "gemini_connection.py").exists()
    for arquivo in list((API_DIR / "backend").rglob("*.py")) + [API_DIR / "server.py"]:
        assert "google.generativeai" not in arquivo.read_text(encoding="utf-8"), arquivo


# ---------- API real (opcional) ----------

@pytest.mark.skipif(not CHAVE_REAL,
                    reason="defina COPMED_GEMINI_REAL=1 e GEMINI_API_KEY para chamar o Gemini")
def test_real_conversa_reaproveita_a_sessao():
    provedor = GeminiProvider(api_key=CHAVE_REAL)
    historico = [_msg("user", "Paciente com febre há 3 dias. Responda só 'ok'.")]
    resposta = provedor.enviar_mensagem("real", historico, historico[0]["parts"][0]["text"])
    historico += [_msg("model", resposta), _msg("user", "Qual sintoma eu citei? Uma palavra.")]
    segunda = provedor.enviar_mensagem("real", historico, "Qual sintoma eu citei? Uma palavra.")
    assert "febre" in segunda.lower()
