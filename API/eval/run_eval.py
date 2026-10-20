#!/usr/bin/env python3
"""run_eval.py v1 (B46 / US022): avaliacao automatica da geracao de SOAP.

Para cada caso de referencia, pede um SOAP a um provedor e mede, POR CASO e
AGREGADO, o que docs/09 secao 3.2 define para esta versao:

    JSON valido   o SOAP passa no `SoapV1` na 1a tentativa (meta 100 % com 1 retry)
    Completude    as 4 secoes (S, O, A, P) com >= 20 palavras (meta >= 90 % dos casos)
    Latencia      p50 / p95 por caso (meta: SOAP p95 <= 20 s)
    Custo         tokens x preco de tabela + minutos de audio x preco de tabela
                  (EQUIVALENTE: o gasto real do projeto e R$ 0, free tier)

e escreve `eval/reports/YYYY-MM-DD-<provedor>-<prompt_versao>.md` (mais um .json
irmao, para comparar relatorios). WER, acerto de papel, CID-10, alucinacao de
exame e referencias inventadas ficam para a B57 (`run_eval` completo).

Uso (a partir de API/):

    python eval/run_eval.py                           # provedor mock, casos de eval/cases
    python eval/run_eval.py --provedor gemini         # usa GEMINI_API_KEY do .env
    python eval/run_eval.py --casos tests/fixtures/cases --limite 3 --estrito

O relatorio NAO contem texto de caso nem saida do modelo: so metricas, ids e
rotulos de erro (o mesmo cuidado da auditoria da B36).

Provedores sao plugaveis (`Provedor.gerar`). Quando a B40 entregar o gerador de
SOAP e o prompt versionado, um novo provedor os encapsula aqui, sem mexer nas
metricas.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import wave
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import ValidationError

EVAL_DIR = Path(__file__).resolve().parent
API_DIR = EVAL_DIR.parent
if str(API_DIR) not in sys.path:  # permite `python eval/run_eval.py` de qualquer pasta
    sys.path.insert(0, str(API_DIR))

SECOES = ("subjetivo", "objetivo", "avaliacao", "plano")
MIN_PALAVRAS = 20

# Metas v5.0 (docs/09 secao 3.2) que esta versao mede.
META_JSON_FINAL_PCT = 100.0
META_COMPLETUDE_PCT = 90.0
META_P95_S = 20.0

MODELO_GEMINI_PADRAO = "gemini-2.5-flash"  # docs/12: Gemini 2.5 Flash, free tier
PAUSA_GEMINI_PADRAO_S = 13.0  # o free tier limita requisicoes por minuto
PROMPT_PADRAO = EVAL_DIR / "prompts" / "soap-provisorio-v1.txt"
PRECOS_PADRAO = EVAL_DIR / "precos.json"
CASOS_PADRAO = EVAL_DIR / "cases"
RELATORIOS_PADRAO = EVAL_DIR / "reports"


# ---------------------------------------------------------------------------
# Casos de referencia
# ---------------------------------------------------------------------------

class CasoInvalido(ValueError):
    """Arquivo de caso fora do formato de docs/09 secao 3.1."""


def validar_caso(caso, origem: str) -> None:
    if not isinstance(caso, dict):
        raise CasoInvalido(f"{origem}: o caso deve ser um objeto JSON")
    if not isinstance(caso.get("id"), str) or not caso["id"].strip():
        raise CasoInvalido(f"{origem}: falta o campo 'id' (texto)")
    transcricao = caso.get("transcricao")
    if not isinstance(transcricao, list) or not transcricao:
        raise CasoInvalido(f"{origem}: 'transcricao' deve ser uma lista nao vazia de {{papel, texto}}")
    for turno in transcricao:
        if not (isinstance(turno, dict) and isinstance(turno.get("papel"), str) and isinstance(turno.get("texto"), str)):
            raise CasoInvalido(f"{origem}: cada turno da 'transcricao' precisa de 'papel' e 'texto' (texto)")
    for campo, tipo in (("prontuario", dict), ("pdfs", list), ("gabarito", dict), ("pii_plantada", list)):
        if campo in caso and not isinstance(caso[campo], tipo):
            raise CasoInvalido(f"{origem}: '{campo}' deve ser {'objeto' if tipo is dict else 'lista'}")
    duracao = caso.get("duracao_min")
    if duracao is not None and (isinstance(duracao, bool) or not isinstance(duracao, (int, float)) or duracao < 0):
        raise CasoInvalido(f"{origem}: 'duracao_min' deve ser um numero >= 0")


def _carregar_documentos(caso: dict, pasta_pdfs: Path) -> dict[str, str]:
    """Texto dos anexos listados em `pdfs`, lidos de <casos>/pdfs/<nome>. Ausente => ignorado."""
    documentos = {}
    for nome in caso.get("pdfs") or []:
        arquivo = pasta_pdfs / str(nome)
        if arquivo.is_file():
            documentos[str(nome)] = arquivo.read_text(encoding="utf-8")
    return documentos


def carregar_casos(pasta: Path, limite: int | None = None) -> list[dict]:
    pasta = Path(pasta)
    if not pasta.is_dir():
        raise CasoInvalido(f"pasta de casos nao encontrada: {pasta}")
    arquivos = sorted(pasta.glob("*.json"))
    if not arquivos:
        raise CasoInvalido(f"nenhum arquivo .json em {pasta}")
    casos, ids = [], set()
    for arquivo in arquivos:
        try:
            caso = json.loads(arquivo.read_text(encoding="utf-8"))
        except json.JSONDecodeError as erro:
            raise CasoInvalido(f"{arquivo.name}: JSON malformado (linha {erro.lineno}, coluna {erro.colno})") from erro
        validar_caso(caso, arquivo.name)
        if caso["id"] in ids:
            raise CasoInvalido(f"{arquivo.name}: id duplicado '{caso['id']}'")
        ids.add(caso["id"])
        caso["_documentos"] = _carregar_documentos(caso, pasta / "pdfs")
        casos.append(caso)
    return casos[:limite] if limite else casos


def montar_conteudo_caso(caso: dict) -> str:
    """Texto enviado ao modelo para um caso (o prompt vai a parte, como instrucao)."""
    partes = ["## Prontuario"]
    prontuario = caso.get("prontuario") or {}
    partes += [f"- {chave}: {valor}" for chave, valor in prontuario.items()] or ["(vazio)"]
    partes += ["", "## Transcricao da consulta"]
    for turno in caso["transcricao"]:
        rotulo = {"medico": "Medico", "paciente": "Paciente"}.get(turno["papel"].lower(), turno["papel"])
        partes.append(f"{rotulo}: {turno['texto']}")
    documentos = caso.get("_documentos") or {}
    if documentos:
        partes += ["", "## Documentos anexados"]
        for nome, texto in documentos.items():
            partes += [f"[{nome}]", texto]
    return "\n".join(partes)


def minutos_de_audio(caso: dict) -> float:
    """`duracao_min` do caso; senao a duracao do .wav indicado em `audio` (relativo a eval/audio)."""
    if isinstance(caso.get("duracao_min"), (int, float)):
        return float(caso["duracao_min"])
    arquivo = caso.get("audio")
    if isinstance(arquivo, str):
        caminho = EVAL_DIR / "audio" / arquivo
        if caminho.is_file():
            try:
                with wave.open(str(caminho), "rb") as wav:
                    return wav.getnframes() / float(wav.getframerate()) / 60.0
            except (wave.Error, EOFError):
                return 0.0
    return 0.0


# ---------------------------------------------------------------------------
# Schema do SOAP
# ---------------------------------------------------------------------------

def carregar_schema():
    """(SoapV1, origem). Usa o oficial (B39, `soap/schema.py`) se ja existir."""
    try:
        from soap.schema import SoapV1  # type: ignore[import-not-found]

        return SoapV1, "oficial (soap/schema.py)"
    except ModuleNotFoundError as erro:
        if erro.name not in ("soap", "soap.schema"):
            raise
    from eval.soap_provisorio import SoapV1

    return SoapV1, "provisorio (eval/soap_provisorio.py; sera substituido pelo da B39)"


def resumir_erro_validacao(erro: ValidationError) -> str:
    """Caminho e tipo de cada falha, SEM o valor recebido (que seria saida do modelo)."""
    itens = [f"{'.'.join(str(p) for p in e['loc']) or '(raiz)'}: {e['type']}" for e in erro.errors()[:5]]
    extra = len(erro.errors()) - len(itens)
    return "; ".join(itens) + (f" (+{extra})" if extra > 0 else "")


def validar_soap(texto, schema):
    """(objeto, None) se valido; (None, motivo) se nao. Estrito: JSON puro, sem cerca de codigo."""
    if not isinstance(texto, str):
        return None, "resposta nao e texto"
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as erro:
        return None, f"JSON malformado (linha {erro.lineno}, coluna {erro.colno})"
    if not isinstance(dados, dict):
        return None, "o JSON nao e um objeto"
    try:
        return schema.model_validate(dados), None
    except ValidationError as erro:
        return None, resumir_erro_validacao(erro)


def contar_palavras(texto) -> int:
    """Palavras = pedacos separados por espaco que contem letra ou numero."""
    if not isinstance(texto, str):
        return 0
    return sum(1 for pedaco in texto.split() if any(c.isalnum() for c in pedaco))


# ---------------------------------------------------------------------------
# Provedores
# ---------------------------------------------------------------------------

@dataclass
class Resposta:
    texto: str
    tokens_entrada: int
    tokens_saida: int
    estimado: bool = False  # True quando o provedor nao informou tokens


def _estimar_tokens(texto: str) -> int:
    return max(1, round(len(texto) / 4))


class ProvedorMock:
    """Offline e deterministico: monta um SOAP valido a partir do gabarito do caso.

    Serve para validar o harness e rodar no CI sem chave. NAO mede IA nenhuma: o
    relatorio traz um aviso em destaque quando este provedor e usado.
    """

    nome = "mock"
    modelo = "mock"
    modelo_preco = MODELO_GEMINI_PADRAO

    def gerar(self, caso: dict, erro_anterior: str | None = None) -> Resposta:
        conteudo = montar_conteudo_caso(caso)
        gabarito = caso.get("gabarito") or {}
        soap = gabarito.get("soap") or {}
        palavras = " ".join(t["texto"] for t in caso["transcricao"]).split() or ["Sem", "informacao"]
        secoes = {}
        for indice, secao in enumerate(SECOES):
            texto = soap.get(secao)
            if not isinstance(texto, str) or not texto.strip():
                texto = " ".join(palavras[indice * 30:(indice + 1) * 30]) or "Sem informacao"
            secoes[secao] = texto
        saida = {
            **secoes,
            "hipoteses": [
                {"descricao": f"Hipotese compativel com CID-10 {cid}", "cid10": str(cid), "confianca": "media"}
                for cid in gabarito.get("cid10") or []
            ],
            "alertas": [],
            "pendencias": [str(p) for p in gabarito.get("pendencias_esperadas") or []],
        }
        texto = json.dumps(saida, ensure_ascii=False)
        return Resposta(texto, _estimar_tokens(conteudo), _estimar_tokens(texto), estimado=True)


class _ModeloGenai:
    """Cliente google-genai (B41) com o `generate_content(conteudo)` usado aqui."""

    def __init__(self, api_key: str, modelo: str, prompt: str, genai_mod=None):
        genai = genai_mod  # testes injetam um SDK falso
        if genai is None:
            from google import genai

        self._cliente = genai.Client(api_key=api_key)
        self._modelo = modelo
        self._config = {
            "system_instruction": prompt,
            "response_mime_type": "application/json",
            "temperature": 0.2,
        }

    def generate_content(self, conteudo: str):
        resposta = self._cliente.models.generate_content(
            model=self._modelo, contents=conteudo, config=self._config,
        )
        if not resposta.text:
            # google-genai devolve text=None em vez de levantar quando bloqueia
            raise ValueError("resposta bloqueada ou vazia")
        return resposta


class ProvedorGemini:
    """Gemini via google-genai (ja e dependencia do projeto, importada so ao usar).

    `response_mime_type=application/json` pede JSON puro; o esquema NAO e imposto
    pela API de proposito: a metrica "JSON valido" mede o que o modelo produz, e
    forcar `response_schema` a tornaria quase trivial. A B40 decide isso no prompt
    de producao.
    """

    nome = "gemini"

    def __init__(self, api_key: str, modelo: str, prompt: str, modelo_generativo=None):
        self.modelo = modelo
        self.modelo_preco = modelo
        if modelo_generativo is None:
            modelo_generativo = _ModeloGenai(api_key, modelo, prompt)
        self._modelo = modelo_generativo

    def gerar(self, caso: dict, erro_anterior: str | None = None) -> Resposta:
        conteudo = montar_conteudo_caso(caso)
        if erro_anterior:
            conteudo += (
                f"\n\nA resposta anterior foi rejeitada na validacao ({erro_anterior}). "
                "Responda novamente apenas com o objeto JSON valido."
            )
        resposta = self._modelo.generate_content(conteudo)
        texto = resposta.text  # bloqueada/vazia ja levantou ValueError: tratado como erro do provedor
        uso = getattr(resposta, "usage_metadata", None)
        entrada = int(getattr(uso, "prompt_token_count", 0) or 0)
        candidatos = int(getattr(uso, "candidates_token_count", 0) or 0)
        # O "pensamento" do 2.5 e cobrado como SAIDA. Quando a resposta nao traz
        # `thoughts_token_count`, o total, que o inclui, permite derivar.
        pensamento = getattr(uso, "thoughts_token_count", None)
        if pensamento is None:
            total = int(getattr(uso, "total_token_count", 0) or 0)
            pensamento = max(0, total - entrada - candidatos)
        saida = candidatos + int(pensamento or 0)
        if entrada == 0 and saida == 0:
            return Resposta(texto, _estimar_tokens(conteudo), _estimar_tokens(texto), estimado=True)
        return Resposta(texto, entrada, saida)


def classificar_erro_provedor(erro: Exception) -> str:
    """Rotulo curto para o relatorio. Nunca a mensagem: ela pode trazer pedacos do pedido."""
    tipo = type(erro).__name__
    texto = f"{tipo} {erro}".lower()
    if "429" in texto or "quota" in texto or "resourceexhausted" in texto or "rate limit" in texto:
        rotulo = "limite de cota ou de taxa (429)"
    elif "api key" in texto or "api_key" in texto or "permission" in texto or "unauthenticated" in texto:
        rotulo = "chave invalida ou sem permissao"
    elif "timeout" in texto or "deadline" in texto or "timed out" in texto:
        rotulo = "tempo esgotado"
    elif isinstance(erro, ValueError):
        rotulo = "resposta bloqueada ou vazia"
    else:
        rotulo = "erro do provedor"
    return f"{rotulo} [{tipo}]"


# ---------------------------------------------------------------------------
# Custo equivalente
# ---------------------------------------------------------------------------

def carregar_precos(caminho: Path) -> dict:
    try:
        precos = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as erro:
        raise ValueError(f"tabela de precos ilegivel ({caminho}): {type(erro).__name__}") from erro
    if not isinstance(precos.get("modelos"), dict) or not isinstance(precos.get("usd_brl"), (int, float)):
        raise ValueError(f"tabela de precos invalida ({caminho}): faltam 'modelos' e 'usd_brl'")
    return precos


def calcular_custo_brl(precos: dict, modelo: str, tokens_entrada: int, tokens_saida: int, minutos_audio: float):
    """R$ equivalente, ou None se o modelo nao esta na tabela."""
    tabela = precos["modelos"].get(modelo)
    if not tabela:
        return None
    usd = (
        tokens_entrada / 1e6 * tabela["entrada_usd_por_milhao_tokens"]
        + tokens_saida / 1e6 * tabela["saida_usd_por_milhao_tokens"]
        + minutos_audio * tabela.get("audio_usd_por_minuto", 0.0)
    )
    return usd * precos["usd_brl"]


# ---------------------------------------------------------------------------
# Avaliacao de um caso
# ---------------------------------------------------------------------------

@dataclass
class Tentativa:
    valida: bool
    motivo: str | None
    latencia_s: float
    tokens_entrada: int
    tokens_saida: int


@dataclass
class ResultadoCaso:
    id: str
    tentativas: list[Tentativa] = field(default_factory=list)
    erro_provedor: str | None = None
    palavras: dict[str, int] | None = None
    minutos_audio: float = 0.0
    custo_brl: float | None = None
    tokens_estimados: bool = False

    @property
    def avaliado(self) -> bool:
        return self.erro_provedor is None

    @property
    def valido_1a(self) -> bool:
        return bool(self.tentativas) and self.tentativas[0].valida

    @property
    def valido_final(self) -> bool:
        return any(t.valida for t in self.tentativas)

    @property
    def completo(self) -> bool:
        return bool(self.palavras) and all(self.palavras.get(s, 0) >= MIN_PALAVRAS for s in SECOES)

    @property
    def latencia_total_s(self) -> float:
        return sum(t.latencia_s for t in self.tentativas)

    @property
    def tokens_entrada(self) -> int:
        return sum(t.tokens_entrada for t in self.tentativas)

    @property
    def tokens_saida(self) -> int:
        return sum(t.tokens_saida for t in self.tentativas)


def avaliar_caso(caso: dict, provedor, schema, precos: dict, max_tentativas: int = 2) -> ResultadoCaso:
    """Gera o SOAP e mede. Uma tentativa extra (retry) se o JSON for invalido, como em docs/09."""
    resultado = ResultadoCaso(id=caso["id"], minutos_audio=minutos_de_audio(caso))
    erro_anterior = None
    for _ in range(max_tentativas):
        inicio = time.perf_counter()
        try:
            resposta = provedor.gerar(caso, erro_anterior)
        except Exception as erro:  # qualquer falha do provedor: registra e segue para o proximo caso
            resultado.erro_provedor = classificar_erro_provedor(erro)
            break
        latencia = time.perf_counter() - inicio
        objeto, motivo = validar_soap(resposta.texto, schema)
        resultado.tentativas.append(
            Tentativa(objeto is not None, motivo, latencia, resposta.tokens_entrada, resposta.tokens_saida)
        )
        resultado.tokens_estimados = resultado.tokens_estimados or resposta.estimado
        if objeto is not None:
            dados = objeto.model_dump()
            resultado.palavras = {secao: contar_palavras(dados.get(secao)) for secao in SECOES}
            break
        erro_anterior = motivo
    resultado.custo_brl = calcular_custo_brl(
        precos, provedor.modelo_preco, resultado.tokens_entrada, resultado.tokens_saida, resultado.minutos_audio
    )
    return resultado


# ---------------------------------------------------------------------------
# Agregados
# ---------------------------------------------------------------------------

def percentil(valores: list[float], p: float):
    """Percentil pelo metodo do posto mais proximo (nearest-rank). None se nao ha valores."""
    if not valores:
        return None
    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(p / 100.0 * len(ordenados)) - 1)]


def _pct(parte: int, total: int):
    return 100.0 * parte / total if total else None


def agregar(resultados: list[ResultadoCaso]) -> dict:
    """Agregados sobre os casos AVALIADOS (os que o provedor respondeu); erros sao contados a parte."""
    avaliados = [r for r in resultados if r.avaliado]
    n = len(avaliados)
    latencias = [r.latencia_total_s for r in avaliados]
    custos = [r.custo_brl for r in avaliados if r.custo_brl is not None]
    agregado = {
        "casos_total": len(resultados),
        "casos_avaliados": n,
        "casos_com_erro_de_provedor": len(resultados) - n,
        "json_valido_1a_pct": _pct(sum(r.valido_1a for r in avaliados), n),
        "json_valido_final_pct": _pct(sum(r.valido_final for r in avaliados), n),
        "completude_pct": _pct(sum(r.completo for r in avaliados), n),
        "latencia_p50_s": percentil(latencias, 50),
        "latencia_p95_s": percentil(latencias, 95),
        "tokens_entrada_total": sum(r.tokens_entrada for r in avaliados),
        "tokens_saida_total": sum(r.tokens_saida for r in avaliados),
        "custo_total_brl": sum(custos) if custos else None,
        "custo_medio_por_caso_brl": (sum(custos) / len(custos)) if custos else None,
        "tokens_estimados": any(r.tokens_estimados for r in avaliados),
    }
    return agregado


def avaliar_metas(agregado: dict) -> dict[str, str]:
    """'ok' | 'abaixo da meta' | 'sem dados' por metrica com meta (as demais sao informativas)."""

    def comparar(valor, meta, maior_melhor=True):
        if valor is None:
            return "sem dados"
        return "ok" if (valor >= meta if maior_melhor else valor <= meta) else "abaixo da meta"

    return {
        "json_valido_final": comparar(agregado["json_valido_final_pct"], META_JSON_FINAL_PCT),
        "completude": comparar(agregado["completude_pct"], META_COMPLETUDE_PCT),
        "latencia_p95": comparar(agregado["latencia_p95_s"], META_P95_S, maior_melhor=False),
    }


# ---------------------------------------------------------------------------
# Relatorio
# ---------------------------------------------------------------------------

def _num(valor, casas=1) -> str:
    return "n/d" if valor is None else f"{valor:.{casas}f}".replace(".", ",")


def _pct_txt(valor) -> str:
    return "n/d" if valor is None else f"{valor:.1f}%".replace(".", ",")


def _brl(valor, casas=4) -> str:
    return "n/d" if valor is None else "R$ " + _num(valor, casas)


def nome_relatorio(data: date, provedor: str, prompt_versao: str) -> str:
    return f"{data.isoformat()}-{provedor}-{prompt_versao}.md"


def gerar_markdown(meta: dict, resultados: list[ResultadoCaso], agregado: dict, metas: dict, precos: dict) -> str:
    texto = [
        "# Relatório de avaliação da IA (run_eval v1)",
        "",
        f"- **Data:** {meta['data']}",
        f"- **Provedor:** {meta['provedor']} (modelo: {meta['modelo']})",
        f"- **Prompt:** {meta['prompt_versao']}",
        f"- **Schema do SOAP:** {meta['schema']}",
        f"- **Casos:** {agregado['casos_total']} "
        f"({agregado['casos_avaliados']} avaliados, {agregado['casos_com_erro_de_provedor']} com erro do provedor)",
        f"- **Pasta de casos:** `{meta['casos']}`",
        "",
    ]
    if meta["provedor"] == "mock":
        texto += [
            "> **AVISO: provedor MOCK.** O SOAP é montado a partir do próprio gabarito, sem IA. "
            "Estes números validam o harness, **não** a qualidade do modelo. Não use para comparar versões.",
            "",
        ]
    if agregado["casos_com_erro_de_provedor"]:
        texto += [
            f"> **AVISO: {agregado['casos_com_erro_de_provedor']} caso(s) sem resposta do provedor** "
            "(ver 'Casos com problema'). Os agregados cobrem só os casos avaliados.",
            "",
        ]
    if not precos.get("verificado"):
        texto += [
            "> **AVISO: tabela de preços ilustrativa** (`eval/precos.json`, `verificado: false`). "
            "O custo abaixo é uma ordem de grandeza, não um orçamento.",
            "",
        ]
    if agregado["tokens_estimados"]:
        texto += ["> Tokens **estimados** (4 caracteres por token): o provedor não informou o uso real.", ""]

    texto += [
        "## Resultado agregado",
        "",
        "| Métrica | Resultado | Meta v5.0 | Situação |",
        "|---|---|---|---|",
        f"| JSON válido na 1ª tentativa | {_pct_txt(agregado['json_valido_1a_pct'])} | informativo | info |",
        f"| JSON válido (com 1 retry) | {_pct_txt(agregado['json_valido_final_pct'])} | 100% | {metas['json_valido_final']} |",
        f"| Completude (4 seções com >= {MIN_PALAVRAS} palavras) | {_pct_txt(agregado['completude_pct'])} | >= 90% | {metas['completude']} |",
        f"| Latência p50 | {_num(agregado['latencia_p50_s'], 2)} s | informativo | info |",
        f"| Latência p95 | {_num(agregado['latencia_p95_s'], 2)} s | <= 20 s | {metas['latencia_p95']} |",
        f"| Tokens (entrada / saida) | {agregado['tokens_entrada_total']} / {agregado['tokens_saida_total']} | informativo | info |",
        f"| Custo equivalente médio por caso | {_brl(agregado['custo_medio_por_caso_brl'])} | "
        f"referência <= {_brl(precos.get('referencia_brl_por_consulta_20min'), 2)} por consulta de 20 min | info |",
        f"| Custo equivalente total | {_brl(agregado['custo_total_brl'])} | informativo | info |",
        "",
        "Completude e latência contam o caso após o retry; um SOAP inválido nas duas tentativas conta como incompleto.",
        "",
        "## Por caso",
        "",
        "| Caso | JSON 1ª | JSON final | Tent. | Palavras S/O/A/P | Completo | Latência (s) | Tokens ent./saída | Custo (R$) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    sim_nao = {True: "sim", False: "não"}
    for r in resultados:
        if not r.avaliado:
            texto.append(f"| {r.id} | - | - | {len(r.tentativas)} | - | - | - | - | - |")
            continue
        palavras = "/".join(str(r.palavras[s]) for s in SECOES) if r.palavras else "-"
        texto.append(
            f"| {r.id} | {sim_nao[r.valido_1a]} | {sim_nao[r.valido_final]} | {len(r.tentativas)} | {palavras} | "
            f"{sim_nao[r.completo]} | {_num(r.latencia_total_s, 2)} | {r.tokens_entrada}/{r.tokens_saida} | "
            f"{_num(r.custo_brl, 4)} |"
        )

    problemas = [r for r in resultados if not r.avaliado or not r.valido_1a or not r.completo]
    texto += ["", "## Casos com problema", ""]
    if not problemas:
        texto.append("Nenhum.")
    for r in problemas:
        if not r.avaliado:
            texto.append(f"- **{r.id}**: sem resposta do provedor: {r.erro_provedor}")
            continue
        itens = []
        for numero, t in enumerate(r.tentativas, 1):
            if not t.valida:
                itens.append(f"tentativa {numero} inválida ({t.motivo})")
        if r.valido_final and not r.completo and r.palavras:
            curtas = [s for s in SECOES if r.palavras[s] < MIN_PALAVRAS]
            itens.append(f"seção(ões) curta(s): {', '.join(curtas)}")
        texto.append(f"- **{r.id}**: " + "; ".join(itens))

    texto += [
        "",
        "## Preços usados (por modelo)",
        "",
        f"Câmbio: US$ 1 = R$ {_num(precos['usd_brl'], 2)}. Tabela `verificado`: {sim_nao[bool(precos.get('verificado'))]}.",
        "",
        "| Modelo | Entrada (US$/1M tokens) | Saída (US$/1M tokens) | Áudio (US$/min) |",
        "|---|---|---|---|",
    ]
    for modelo, tabela in precos["modelos"].items():
        texto.append(
            f"| {modelo} | {_num(tabela['entrada_usd_por_milhao_tokens'], 2)} | "
            f"{_num(tabela['saida_usd_por_milhao_tokens'], 2)} | {_num(tabela.get('audio_usd_por_minuto', 0), 5)} |"
        )
    texto += [
        "",
        "Gasto real do projeto: R$ 0 (free tier, docs/12). Custo acima = equivalente a preços de tabela.",
        "",
    ]
    return "\n".join(texto)


def dados_json(meta: dict, resultados: list[ResultadoCaso], agregado: dict, metas: dict) -> dict:
    """Versao legivel por maquina (para comparar relatorios entre prompts/provedores)."""
    return {
        "meta": meta,
        "agregado": agregado,
        "metas": metas,
        "casos": [
            {
                "id": r.id,
                "erro_provedor": r.erro_provedor,
                "valido_1a": r.valido_1a,
                "valido_final": r.valido_final,
                "completo": r.completo,
                "palavras": r.palavras,
                "latencia_total_s": round(r.latencia_total_s, 4),
                "tokens_entrada": r.tokens_entrada,
                "tokens_saida": r.tokens_saida,
                "minutos_audio": round(r.minutos_audio, 4),
                "custo_brl": r.custo_brl,
                "tentativas": [
                    {"valida": t.valida, "motivo": t.motivo, "latencia_s": round(t.latencia_s, 4)} for t in r.tentativas
                ],
            }
            for r in resultados
        ],
    }


# ---------------------------------------------------------------------------
# Execucao
# ---------------------------------------------------------------------------

def executar(casos, provedor, schema, precos, pausa_s: float = 0.0, log=print) -> list[ResultadoCaso]:
    resultados = []
    for indice, caso in enumerate(casos, 1):
        if indice > 1 and pausa_s > 0:
            time.sleep(pausa_s)
        resultado = avaliar_caso(caso, provedor, schema, precos)
        resultados.append(resultado)
        if not resultado.avaliado:
            situacao = f"ERRO DO PROVEDOR: {resultado.erro_provedor}"
        else:
            situacao = (
                f"json {'ok' if resultado.valido_final else 'INVALIDO'}"
                f"{' (1a)' if resultado.valido_1a else ' (com retry)' if resultado.valido_final else ''}, "
                f"{'completo' if resultado.completo else 'INCOMPLETO'}, {resultado.latencia_total_s:.2f}s"
            )
        log(f"[{indice}/{len(casos)}] {caso['id']}: {situacao}")
    return resultados


def construir_provedor(args, prompt_texto: str):
    if args.provedor == "mock":
        return ProvedorMock()
    chave = os.environ.get("GEMINI_API_KEY", "").strip()
    if not chave:
        raise ValueError("GEMINI_API_KEY nao definida (coloque em API/.env). Para testar o harness sem chave: --provedor mock")
    return ProvedorGemini(chave, args.modelo, prompt_texto)


def ler_argumentos(argv=None):
    ap = argparse.ArgumentParser(description="Avaliacao da geracao de SOAP (B46, run_eval v1).")
    ap.add_argument("--provedor", choices=("mock", "gemini"), default=os.environ.get("EVAL_PROVEDOR", "mock"))
    ap.add_argument("--casos", type=Path, default=CASOS_PADRAO, help="pasta com os casos .json (padrao: eval/cases)")
    ap.add_argument("--saida", type=Path, default=RELATORIOS_PADRAO, help="pasta do relatorio (padrao: eval/reports)")
    ap.add_argument("--prompt", type=Path, default=PROMPT_PADRAO, help="arquivo do prompt; o nome vira a versao")
    ap.add_argument("--modelo", default=MODELO_GEMINI_PADRAO, help="modelo do provedor gemini")
    ap.add_argument("--precos", type=Path, default=PRECOS_PADRAO)
    ap.add_argument("--limite", type=int, default=None, help="roda so os N primeiros casos")
    ap.add_argument("--pausa", type=float, default=None, help="segundos entre casos (padrao: 0 no mock, 13 no gemini)")
    ap.add_argument("--data", default=None, help="AAAA-MM-DD do relatorio (padrao: hoje)")
    ap.add_argument("--estrito", action="store_true", help="sai com codigo 1 se alguma meta nao for atingida")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    for fluxo in (sys.stdout, sys.stderr):  # o console do Windows (cp1252) nao deve derrubar o relatorio
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(errors="replace")
    args = ler_argumentos(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(API_DIR / ".env")
    except ImportError:
        pass

    try:
        casos = carregar_casos(args.casos, args.limite)
        precos = carregar_precos(args.precos)
        prompt_texto = Path(args.prompt).read_text(encoding="utf-8")
        schema, origem_schema = carregar_schema()
        provedor = construir_provedor(args, prompt_texto)
        data = date.fromisoformat(args.data) if args.data else date.today()
    except (CasoInvalido, ValueError, OSError) as erro:
        print(f"erro: {erro}", file=sys.stderr)
        if isinstance(erro, CasoInvalido) and not args.casos.exists() and args.casos == CASOS_PADRAO:
            print("      (os 20 casos entram com a B45; enquanto isso use --casos tests/fixtures/cases)", file=sys.stderr)
        return 2

    pausa = args.pausa if args.pausa is not None else (PAUSA_GEMINI_PADRAO_S if args.provedor == "gemini" else 0.0)
    prompt_versao = Path(args.prompt).stem
    print(f"run_eval v1: {len(casos)} caso(s), provedor {provedor.nome} ({provedor.modelo}), prompt {prompt_versao}")

    resultados = executar(casos, provedor, schema, precos, pausa)
    agregado = agregar(resultados)
    metas = avaliar_metas(agregado)
    meta = {
        "data": data.isoformat(),
        "provedor": provedor.nome,
        "modelo": provedor.modelo,
        "prompt_versao": prompt_versao,
        "schema": origem_schema,
        "casos": str(args.casos),
    }

    args.saida.mkdir(parents=True, exist_ok=True)
    base = args.saida / nome_relatorio(data, provedor.nome, prompt_versao)
    base.write_text(gerar_markdown(meta, resultados, agregado, metas, precos), encoding="utf-8")
    base.with_suffix(".json").write_text(
        json.dumps(dados_json(meta, resultados, agregado, metas), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"JSON valido (com retry): {_pct_txt(agregado['json_valido_final_pct'])} | "
          f"completude: {_pct_txt(agregado['completude_pct'])} | p95: {_num(agregado['latencia_p95_s'], 2)} s | "
          f"custo medio/caso: {_brl(agregado['custo_medio_por_caso_brl'])}")
    print(f"Relatorio: {base}")

    if args.estrito:
        falhas = [nome for nome, situacao in metas.items() if situacao != "ok"]
        if agregado["casos_com_erro_de_provedor"]:
            falhas.append("casos sem resposta do provedor")
        if falhas:
            print(f"--estrito: metas nao atingidas: {', '.join(falhas)}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
