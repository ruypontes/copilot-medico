"""Partes (chunks) de audio da gravacao, em disco ate a transcricao (B30).

A extensao envia a gravacao em partes de ate 5 min (US017-CA003). Aqui ficam
a validacao do que chega e o arquivo temporario de cada parte; os metadados
(sequencia, duracao) vao para a tabela `parte_audio`.

O audio nunca e persistido alem da transcricao (US017-CA007): quem chama
apaga os arquivos com `apagar()` assim que a gravacao e transcrita, com ou
sem sucesso. O que escapar disso (processo derrubado no meio, por exemplo)
e varrido por `apagar_orfaos()` no job diario (B35).
"""
import re
import tempfile
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

from backend.config import settings

# US017-CA003: cada parte tem no maximo 5 min. A tolerancia cobre o
# arredondamento do codificador do navegador.
MAX_DURACAO_S = 5 * 60
TOLERANCIA_S = 5
# 120 min de gravacao (US017-CA002) dao ~25 partes; o teto so barra lixo.
MAX_SEQ = 1000

# O id da gravacao vira nome de pasta: so caracteres seguros.
_RECORDING_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
# Extensao do audio inteiro da rota legada: vira parte do nome do arquivo.
_EXTENSAO = re.compile(r"^[A-Za-z0-9]{1,5}$")

# Audio inteiro de /api/transcribe_audio: mesma base das partes, para o job
# diario enxergar tudo o que o servidor gravou.
PASTA_AVULSOS = "avulsos"


class ParteInvalida(ValueError):
    """Parte recusada; `status` e o codigo HTTP da resposta."""

    def __init__(self, mensagem: str, status: int = 400):
        super().__init__(mensagem)
        self.status = status


@dataclass(frozen=True)
class ArquivoDeParte:
    caminho: str
    tamanho_bytes: int
    duracao_s: float


def diretorio_base() -> Path:
    if settings.audio_chunks_dir.strip():
        return Path(settings.audio_chunks_dir.strip())
    return Path(tempfile.gettempdir()) / "copmed_audio_chunks"


def validar_recording_id(valor) -> str:
    if not isinstance(valor, str) or not _RECORDING_ID.match(valor.strip()):
        raise ParteInvalida("recording_id e obrigatorio (8 a 64 letras, numeros, '-' ou '_').")
    return valor.strip()


def validar_seq(valor, campo: str = "seq") -> int:
    try:
        seq = int(str(valor).strip())
    except (TypeError, ValueError):
        raise ParteInvalida(f"{campo} deve ser um inteiro a partir de 1.") from None
    if not 1 <= seq <= MAX_SEQ:
        raise ParteInvalida(f"{campo} deve estar entre 1 e {MAX_SEQ}.")
    return seq


def _duracao_wav(caminho: Path) -> float:
    try:
        with wave.open(str(caminho), "rb") as wav:
            taxa = wav.getframerate()
            return wav.getnframes() / taxa if taxa else 0.0
    except (wave.Error, EOFError):
        raise ParteInvalida("audio_file deve ser um WAV PCM valido.") from None


def salvar(arquivo, consulta_id: str, gravacao_id: str, seq: int) -> ArquivoDeParte:
    """Grava a parte em disco e confere formato, tamanho e duracao.

    `consulta_id` e `gravacao_id` ja chegam validados (UUID e
    `validar_recording_id`). Cada envio ganha um nome proprio: num reenvio o
    arquivo antigo so e apagado depois que o novo esta registrado.
    """
    pasta = diretorio_base() / consulta_id / gravacao_id
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{seq:04d}-{uuid.uuid4().hex}.wav"

    try:
        # Dentro do try: upload interrompido no meio deixaria um WAV parcial
        arquivo.save(str(caminho))
        tamanho = caminho.stat().st_size
        if tamanho > settings.audio_chunk_max_mb * 1024 * 1024:
            raise ParteInvalida(
                f"Parte acima de {settings.audio_chunk_max_mb} MB.", status=413
            )
        duracao = _duracao_wav(caminho)
        if duracao <= 0:
            raise ParteInvalida("audio_file esta vazio.")
        if duracao > MAX_DURACAO_S + TOLERANCIA_S:
            raise ParteInvalida(f"Cada parte deve ter no maximo {MAX_DURACAO_S // 60} min.")
    except BaseException:
        apagar([str(caminho)])
        raise
    return ArquivoDeParte(str(caminho), tamanho, duracao)


def salvar_avulso(arquivo, nome_original: str | None = None) -> str:
    """Grava o audio inteiro da rota legada e devolve o caminho.

    Quem chama apaga com `apagar([caminho])` num `finally`. A extensao do nome
    original so e aproveitada se for segura; senao, `.wav`.
    """
    extensao = (nome_original or "").rsplit(".", 1)[-1] if "." in (nome_original or "") else ""
    if not _EXTENSAO.match(extensao):
        extensao = "wav"
    pasta = diretorio_base() / PASTA_AVULSOS
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{uuid.uuid4().hex}.{extensao.lower()}"
    try:
        arquivo.save(str(caminho))
    except BaseException:
        apagar([str(caminho)])
        raise
    return str(caminho)


def apagar(caminhos) -> None:
    """Apaga os arquivos (ausentes sao ignorados) e as pastas que ficarem vazias."""
    base = diretorio_base()
    for caminho in caminhos:
        arquivo = Path(caminho)
        arquivo.unlink(missing_ok=True)
        # <base>/<consulta>/<gravacao>: sobe removendo so o que esvaziou.
        for pasta in (arquivo.parent, arquivo.parent.parent):
            if pasta == base or base not in pasta.parents:
                break
            try:
                pasta.rmdir()
            except OSError:
                break


def apagar_orfaos(idade_minima_s: float, em_uso=()) -> list[str]:
    """Apaga os arquivos da base mais velhos que `idade_minima_s` e fora de
    `em_uso` (caminhos que ainda tem linha em `parte_audio`). Devolve o que
    apagou. A idade minima protege a gravacao e a transcricao em andamento.
    """
    base = diretorio_base()
    if not base.is_dir():
        return []
    protegidos = {str(Path(c).resolve()) for c in em_uso}
    limite = time.time() - idade_minima_s
    apagados = []
    for arquivo in base.rglob("*"):
        try:
            if (not arquivo.is_file() or str(arquivo.resolve()) in protegidos
                    or arquivo.stat().st_mtime > limite):
                continue
        except OSError:
            continue  # apagado por outra requisicao durante a varredura
        apagados.append(str(arquivo))
    apagar(apagados)
    return apagados
