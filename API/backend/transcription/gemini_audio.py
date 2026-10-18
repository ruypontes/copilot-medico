"""Provedor padrao: Gemini audio com marcacao de falantes (B31, ADR-04).

Uma unica chamada ao Gemini transcreve o audio e marca quem fala em cada
turno (medico, paciente, outro). O modelo devolve JSON, convertido aqui para o
contrato comum de `provider.py`. O SDK `google.generativeai` so e importado na
primeira transcricao, para o servidor e os testes subirem sem ele.
"""
import io
import json
import os
import re
import unicodedata
import wave

from .provider import (
    PAPEL_NAO_IDENTIFICADO,
    TranscriptionError,
    TranscriptionProvider,
    montar_resultado,
)

MODELO_PADRAO = "gemini-2.5-flash"

# O Gemini aceita ate ~20 MB por requisicao com o audio embutido (doc 12: os
# chunks de 5 min do B30 ficam abaixo disso). WAV maior (rota legada, audio
# inteiro) e fatiado aqui; nada vai pela File API, entao nenhum audio fica
# armazenado no Google.
LIMITE_INLINE_BYTES = 18 * 1024 * 1024

TIPOS_AUDIO = {
    ".wav": "audio/wav",
    ".mp3": "audio/mp3",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".aiff": "audio/aiff",
    ".webm": "audio/webm",
}

# Papel devolvido pelo modelo -> (role, role_key, speaker_id). role_key segue
# o que a extensao ja entende ("doctor" vai a esquerda no TranscriptionViewer).
PAPEIS = {
    "medico": ("Médico", "doctor", 0),
    "paciente": ("Paciente", "patient", 1),
    "outro": ("Outro", "other", 2),
}
PAPEL_DESCONHECIDO = (PAPEL_NAO_IDENTIFICADO, "unknown", None)

PROMPT = """\
Você recebe a gravação de uma consulta médica em português do Brasil.
Transcreva a fala literalmente, separando-a em turnos: um turno novo a cada \
troca de falante. Para cada turno, marque quem fala:
- "medico": o profissional que conduz a consulta;
- "paciente": a pessoa atendida;
- "outro": acompanhante, enfermagem ou qualquer outra pessoa;
- "desconhecido": quando não for possível saber pelo conteúdo ou pela voz.
Regras: não resuma, não corrija termos, não traduza e não invente falas. \
Trechos inaudíveis viram [inaudível]. Se não houver fala, devolva a lista vazia.
Responda somente com JSON neste formato, com inicio e fim em segundos desde o \
começo do áudio:
{"turnos": [{"falante": "medico", "texto": "...", "inicio": 0.0, "fim": 3.2}]}
"""

GERACAO = {"response_mime_type": "application/json", "temperature": 0}

# Sintomas, remedios e doses disparam os filtros padrao com frequencia; so
# conteudo de risco alto e bloqueado na transcricao.
SEGURANCA = {
    "HARM_CATEGORY_HARASSMENT": "BLOCK_ONLY_HIGH",
    "HARM_CATEGORY_HATE_SPEECH": "BLOCK_ONLY_HIGH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_ONLY_HIGH",
    "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_ONLY_HIGH",
}


def _sem_acento(texto: str) -> str:
    normal = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normal if not unicodedata.combining(c))


def _papel(falante) -> tuple:
    chave = _sem_acento(str(falante or "")).strip().lower()
    return PAPEIS.get(chave, PAPEL_DESCONHECIDO)


def _segundos(valor) -> float:
    """Aceita 12.5, "12.5", "01:05" ou "00:01:05"; invalido vira 0."""
    if isinstance(valor, (int, float)):
        return max(float(valor), 0.0)
    texto = str(valor or "").strip()
    try:
        if ":" in texto:
            total = 0.0
            for parte in texto.split(":"):
                total = total * 60 + float(parte)
            return max(total, 0.0)
        return max(float(texto), 0.0) if texto else 0.0
    except ValueError:
        return 0.0


def _duracao_wav(caminho: str) -> float:
    try:
        with wave.open(caminho, "rb") as wf:
            return wf.getnframes() / float(wf.getframerate() or 1)
    except (wave.Error, EOFError, OSError):
        return 0.0


def _partes_wav(caminho: str, limite: int):
    """Fatia um WAV em arquivos WAV de ate `limite` bytes: (bytes, inicio_s)."""
    with wave.open(caminho, "rb") as wf:
        params = wf.getparams()
        bytes_quadro = params.sampwidth * params.nchannels
        quadros_parte = max((limite - 44) // bytes_quadro, 1)  # 44 = cabecalho
        lidos = 0
        while quadros := wf.readframes(quadros_parte):
            saida = io.BytesIO()
            with wave.open(saida, "wb") as parte:
                parte.setparams(params)
                parte.writeframes(quadros)
            yield saida.getvalue(), lidos / float(params.framerate)
            lidos += len(quadros) // bytes_quadro


def _ler_json(texto: str) -> list:
    """Extrai a lista de turnos da resposta, tolerando cercas ```json."""
    limpo = re.sub(r"^```(?:json)?\s*|\s*```$", "", (texto or "").strip())
    try:
        dados = json.loads(limpo)
    except ValueError as e:
        raise TranscriptionError("Gemini devolveu JSON inválido") from e
    turnos = dados.get("turnos") if isinstance(dados, dict) else dados
    if not isinstance(turnos, list):
        raise TranscriptionError("Gemini não devolveu a lista de turnos")
    return turnos


def converter_turnos(brutos: list) -> list[dict]:
    """Turnos do Gemini -> turnos do contrato (role, role_key, speaker_id...)."""
    turnos = []
    for bruto in brutos:
        if not isinstance(bruto, dict):
            continue
        texto = str(bruto.get("texto") or "").strip()
        if not texto:
            continue
        role, role_key, speaker_id = _papel(bruto.get("falante"))
        inicio = _segundos(bruto.get("inicio"))
        turnos.append({
            "role": role,
            "role_key": role_key,
            "text": texto[0].upper() + texto[1:],
            "speaker_id": speaker_id,
            "start": inicio,
            "end": max(_segundos(bruto.get("fim")), inicio),
        })
    return turnos


class GeminiAudioProvider(TranscriptionProvider):
    nome = "gemini"

    def __init__(self, api_key: str, modelo: str | None = None,
                 timeout: float = 300.0, genai_mod=None):
        self.api_key = api_key
        self.modelo = modelo or MODELO_PADRAO
        self.timeout = timeout
        self._genai_mod = genai_mod  # testes injetam um SDK falso

    def _genai(self):
        if self._genai_mod is None:
            try:
                import google.generativeai as genai
            except ImportError as e:
                raise TranscriptionError("Pacote google-generativeai não instalado") from e
            genai.configure(api_key=self.api_key)
            self._genai_mod = genai
        return self._genai_mod

    def _sem_chave(self, erro: Exception) -> str:
        """Mensagem do erro sem a chave: o SDK a repete na URL (?key=...)."""
        texto = re.sub(r"key=[^&\s\"']+", "key=<redigida>", str(erro))
        return texto.replace(self.api_key, "<redigida>") if self.api_key else texto

    def _pedacos(self, caminho: str):
        """(bytes, mime, inicio_s) de cada requisicao; WAV grande e fatiado."""
        mime = TIPOS_AUDIO.get(os.path.splitext(caminho)[1].lower(), "audio/wav")
        if os.path.getsize(caminho) <= LIMITE_INLINE_BYTES:
            with open(caminho, "rb") as f:
                yield f.read(), mime, 0.0
            return
        if mime != "audio/wav":
            raise TranscriptionError("Áudio acima do limite do Gemini; envie em partes (B30)")
        try:
            for dados, inicio in _partes_wav(caminho, LIMITE_INLINE_BYTES):
                yield dados, mime, inicio
        except wave.Error as e:
            raise TranscriptionError("WAV inválido") from e

    def _gerar(self, modelo, dados: bytes, mime: str) -> str:
        try:
            resposta = modelo.generate_content(
                [PROMPT, {"mime_type": mime, "data": dados}],
                request_options={"timeout": self.timeout},
            )
            # .text levanta quando a resposta foi bloqueada ou veio sem partes
            return resposta.text
        except Exception as e:
            raise TranscriptionError(f"Falha ao chamar o Gemini: {self._sem_chave(e)}") from e

    def processar_audio(self, caminho_audio: str) -> dict:
        modelo = self._genai().GenerativeModel(
            model_name=self.modelo,
            generation_config=GERACAO,
            safety_settings=SEGURANCA,
        )
        turnos = []
        for dados, mime, inicio in self._pedacos(caminho_audio):
            for turno in converter_turnos(_ler_json(self._gerar(modelo, dados, mime))):
                # Tempos do modelo sao relativos ao pedaco enviado
                turno["start"] += inicio
                turno["end"] += inicio
                turnos.append(turno)
        # A duracao do WAV e exata; o fim do ultimo turno e estimativa do modelo
        duracao = _duracao_wav(caminho_audio) or (turnos[-1]["end"] if turnos else 0.0)
        return montar_resultado(turnos, duracao)
