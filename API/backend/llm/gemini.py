"""Gemini pelo SDK google-genai (B41, D-06).

Substitui o antigo backend/gemini_connection.py, que usava o SDK legado
google-generativeai e recriava o modelo e a sessao de chat a cada mensagem.
Aqui o cliente e criado uma vez e a sessao de cada consulta fica em memoria:
a mensagem seguinte reaproveita a sessao enquanto o historico dela for igual
ao do banco. Se o banco mudou por outro caminho (servidor reiniciado, outro
processo, recomendacao que nao grava no historico), a sessao e recriada a
partir do banco, que continua sendo a fonte da verdade.

O SDK so e importado na primeira chamada, para o servidor e os testes subirem
sem ele.
"""
import re
import threading
from collections import OrderedDict
from pathlib import Path

from .provider import LlmError, LlmProvider

MODELO_PADRAO = "gemini-flash-latest"
INSTRUCAO_CHAT = Path(__file__).resolve().parent.parent / "Co-Pilot_medico.txt"

# Mesmos limites do gemini_connection antigo.
SEGURANCA = [
    {"category": categoria, "threshold": "BLOCK_MEDIUM_AND_ABOVE"}
    for categoria in (
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    )
]

# Sessoes guardadas; a menos usada sai primeiro.
MAX_SESSOES = 128


def _cota_esgotada(erro: Exception) -> bool:
    """O google-genai indica cota esgotada com o codigo 429 (RESOURCE_EXHAUSTED);
    o SDK antigo levantava ResourceExhausted."""
    return (
        getattr(erro, "code", None) == 429
        or str(getattr(erro, "status", "") or "").upper() == "RESOURCE_EXHAUSTED"
        or type(erro).__name__ in {"ResourceExhausted", "TooManyRequests"}
    )


def _texto(mensagem: dict) -> str:
    partes = mensagem.get("parts") or []
    return "".join(
        p.get("text", "") if isinstance(p, dict) else str(p) for p in partes
    )


def _conversa(historico: list[dict], texto: str) -> tuple:
    """Historico do banco como ((role, texto), ...), sem a mensagem atual.

    As rotas gravam a pergunta antes de chamar o modelo; ela vai em
    send_message, entao sai do historico para nao chegar duas vezes.
    """
    conversa = []
    for mensagem in historico or []:
        if not isinstance(mensagem, dict) or "role" not in mensagem or "parts" not in mensagem:
            print(f"Aviso: mensagem mal formatada no histórico ignorada: {mensagem}")
            continue
        conversa.append((mensagem["role"], _texto(mensagem)))
    if conversa and conversa[-1] == ("user", texto):
        conversa.pop()
    return tuple(conversa)


class GeminiProvider(LlmProvider):
    nome = "gemini"

    def __init__(self, api_key: str, modelo: str | None = None,
                 instrucao: str | None = None, timeout: float = 120.0,
                 genai_mod=None, max_sessoes: int = MAX_SESSOES):
        self.api_key = api_key
        self.modelo = modelo or MODELO_PADRAO
        if instrucao is None:
            instrucao = INSTRUCAO_CHAT.read_text(encoding="utf-8")
        self.instrucao = instrucao
        self.timeout = timeout
        self.max_sessoes = max_sessoes
        self._genai_mod = genai_mod  # testes injetam um SDK falso
        self._cliente = None
        self._sessoes: OrderedDict = OrderedDict()  # consulta -> (chat, conversa)
        self._trava = threading.Lock()

    def _client(self):
        with self._trava:
            if self._cliente is None:
                genai = self._genai_mod
                if genai is None:
                    try:
                        from google import genai
                    except ImportError as e:
                        raise LlmError("Pacote google-genai não instalado") from e
                self._cliente = genai.Client(
                    api_key=self.api_key,
                    http_options={"timeout": int(self.timeout * 1000)},  # ms
                )
            return self._cliente

    def _sem_chave(self, erro: Exception) -> str:
        """Mensagem do erro sem a chave, caso o SDK a repita."""
        texto = re.sub(r"key=[^&\s\"']+", "key=<redigida>", str(erro))
        return texto.replace(self.api_key, "<redigida>") if self.api_key else texto

    def _falha(self, erro: Exception) -> LlmError:
        return LlmError(f"Falha ao chamar o Gemini: {self._sem_chave(erro)}",
                        cota_esgotada=_cota_esgotada(erro))

    def _texto_da_resposta(self, resposta) -> str:
        try:
            texto = resposta.text
        except Exception as e:
            raise LlmError(f"Resposta do Gemini sem texto: {self._sem_chave(e)}") from e
        if not texto:
            # google-genai devolve None quando a resposta foi bloqueada
            raise LlmError("Gemini devolveu uma resposta vazia ou bloqueada")
        return texto

    def _sessao(self, chave: str, conversa: tuple):
        """Sessao guardada se o historico bate com o banco; senao, uma nova."""
        with self._trava:
            # Sai do cache durante o envio: dois pedidos simultaneos da mesma
            # consulta nao misturam o historico da mesma sessao.
            guardada = self._sessoes.pop(chave, None)
        if guardada is not None and guardada[1] == conversa:
            return guardada[0]
        return self._client().chats.create(
            model=self.modelo,
            config={"system_instruction": self.instrucao, "safety_settings": SEGURANCA},
            history=[{"role": role, "parts": [{"text": texto}]} for role, texto in conversa],
        )

    def enviar_mensagem(self, consulta_id: str, historico: list[dict], texto: str) -> str:
        chave = str(consulta_id)
        conversa = _conversa(historico, texto)
        chat = self._sessao(chave, conversa)
        try:
            resposta = chat.send_message(texto)
        except Exception as e:
            raise self._falha(e) from e
        texto_resposta = self._texto_da_resposta(resposta)
        with self._trava:
            self._sessoes[chave] = (chat, conversa + (("user", texto), ("model", texto_resposta)))
            while len(self._sessoes) > self.max_sessoes:
                self._sessoes.popitem(last=False)
        return texto_resposta

    def gerar(self, prompt: str, instrucao: str | None = None, schema: dict | None = None,
              formato_json: bool = False) -> str:
        config = {"safety_settings": SEGURANCA}
        if instrucao:
            config["system_instruction"] = instrucao
        if formato_json or schema is not None:
            config["response_mime_type"] = "application/json"
        if schema is not None:
            config["response_schema"] = schema
        try:
            resposta = self._client().models.generate_content(
                model=self.modelo, contents=prompt, config=config,
            )
        except LlmError:
            raise
        except Exception as e:
            raise self._falha(e) from e
        return self._texto_da_resposta(resposta)
