"""Provedor Whisper large-v3 via Groq (B32, ADR-04).

Usa a rota compativel com OpenAI da Groq com `response_format=verbose_json`,
que devolve os segmentos com inicio e fim. O Whisper nao separa falantes,
entao todo turno sai como "Falante não identificado", igual ao Diarizador
quando nao ha vetor de voz.
"""
import json
import mimetypes
import os
import urllib.error
import urllib.request
import uuid

from .provider import (
    PAPEL_NAO_IDENTIFICADO,
    TranscriptionError,
    TranscriptionProvider,
    montar_resultado,
)

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def _multipart(campos: dict, nome_arquivo: str, conteudo: bytes) -> tuple[bytes, str]:
    limite = uuid.uuid4().hex
    partes = []
    for chave, valor in campos.items():
        partes.append(
            f'--{limite}\r\nContent-Disposition: form-data; name="{chave}"\r\n\r\n{valor}\r\n'.encode()
        )
    tipo = mimetypes.guess_type(nome_arquivo)[0] or "application/octet-stream"
    partes.append(
        f'--{limite}\r\nContent-Disposition: form-data; name="file"; filename="{nome_arquivo}"\r\n'
        f"Content-Type: {tipo}\r\n\r\n".encode()
        + conteudo
        + b"\r\n"
    )
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


class WhisperGroqProvider(TranscriptionProvider):
    nome = "whisper"

    def __init__(self, api_key: str, modelo: str = "whisper-large-v3",
                 idioma: str = "pt", url: str = GROQ_URL, timeout: float = 120.0):
        self.api_key = api_key
        self.modelo = modelo
        self.idioma = idioma
        self.url = url
        self.timeout = timeout

    def _enviar(self, caminho_audio: str) -> dict:
        with open(caminho_audio, "rb") as f:
            conteudo = f.read()
        corpo, content_type = _multipart(
            {
                "model": self.modelo,
                "language": self.idioma,
                "response_format": "verbose_json",
                "temperature": "0",
            },
            os.path.basename(caminho_audio),
            conteudo,
        )
        req = urllib.request.Request(
            self.url,
            data=corpo,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": content_type,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise TranscriptionError(f"Groq respondeu {e.code}") from e
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise TranscriptionError(f"Falha ao chamar a Groq: {e}") from e

    def processar_audio(self, caminho_audio: str) -> dict:
        dados = self._enviar(caminho_audio)
        segmentos = dados.get("segments") or []
        if not segmentos and (dados.get("text") or "").strip():
            segmentos = [{"start": 0.0, "end": dados.get("duration") or 0.0, "text": dados["text"]}]

        turnos = []
        for seg in segmentos:
            texto = (seg.get("text") or "").strip()
            if not texto:
                continue
            turnos.append({
                "role": PAPEL_NAO_IDENTIFICADO,
                "role_key": "unknown",
                "text": texto[0].upper() + texto[1:],
                "speaker_id": None,
                "start": float(seg.get("start") or 0.0),
                "end": float(seg.get("end") or 0.0),
            })

        duracao = dados.get("duration") or (turnos[-1]["end"] if turnos else 0.0)
        return montar_resultado(turnos, duracao)
