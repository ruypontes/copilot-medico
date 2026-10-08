"""Camada 2 da anonimizacao: nomes proprios (B26 / US016-CA001, ADR-03).

Duas fontes, aplicadas nesta ordem:

1. **Nomes do cadastro.** Se o paciente da consulta se chama "Maria Souza",
   nos sabemos disso - nao ha por que torcer para o NER acertar. Casamento
   exato e deterministico e pega tambem nomes que o modelo erraria.
2. **NER do spaCy (PER/LOC).** Cobre os nomes que aparecem no texto sem
   estar no cadastro: acompanhante, medico citado, bairro, hospital.

O risco conhecido da ADR-03 e mascarar doenca eponima ("Parkinson", "mal de
Chagas", "Crohn") como se fosse gente. `EXCECOES_MEDICAS` existe para isso:
sem ela, "paciente com Alzheimer" viraria "paciente com [PACIENTE_1]" e a
resposta clinica sairia inutil.

O spaCy e carregado sob demanda e pode ser injetado, para que a suite rode
sem o modelo `pt_core_news_lg` (~600 MB) instalado.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Iterable, Sequence

from .nucleo import MapaAnonimizacao, Resultado, _REGEX_TOKEN

TIPO_PESSOA = "PACIENTE"
TIPO_LOCAL = "LOCAL"

ROTULOS_ESTRUTURAIS = frozenset({
    "fonte",
    "sinais vitais",
    "peso",
    "altura",
    "anamnese",
    "notas clinicas",
})

# Rotulos do spaCy que nos interessam.
_ROTULOS = {"PER": TIPO_PESSOA, "PerSON": TIPO_PESSOA, "PERSON": TIPO_PESSOA, "LOC": TIPO_LOCAL}

# Epônimos e termos clinicos que o NER costuma marcar como PER/LOC.
# Mantidos sem acento e em minusculas; a comparacao normaliza os dois lados.
EXCECOES_MEDICAS = frozenset({
    # Doencas e sindromes eponimas
    "alzheimer", "parkinson", "chagas", "crohn", "hodgkin", "down",
    "addison", "cushing", "graves", "basedow", "hashimoto", "paget",
    "raynaud", "sjogren", "wernicke", "korsakoff", "guillain", "barre",
    "guillain-barre", "bell", "huntington", "wilson", "marfan", "turner",
    "klinefelter", "duchenne", "becker", "charcot", "lou gehrig",
    "burkitt", "kaposi", "ewing", "wilms", "bright", "meniere",
    "tourette", "asperger", "reye", "kawasaki", "behcet", "takayasu",
    "wegener", "goodpasture", "berger", "alport", "fanconi", "gilbert",
    "dupuytren", "osgood", "schlatter", "perthes", "scheuermann",
    "barrett", "mallory", "weiss", "zollinger", "ellison", "whipple",
    "boerhaave", "ramsay hunt", "horner", "brown-sequard", "broca",
    "wernicke", "babinski", "romberg", "lasegue", "murphy", "blumberg",
    "mcburney", "cullen", "grey turner", "virchow", "troisier",
    # Escalas, sinais e manobras
    "glasgow", "apgar", "braden", "morse", "ranson", "child", "pugh",
    "wells", "framingham", "borg", "karnofsky", "barthel", "katz",
    # Unidades e epônimos de aparelho
    "celsius", "fahrenheit", "kelvin", "pascal", "newton", "hertz",
    "doppler", "holter", "swan-ganz", "foley", "kocher",
})


def _normalizar_nome(texto: str) -> str:
    """Minusculas, sem acento e sem pontuacao, para comparar nomes."""
    semacento = unicodedata.normalize("NFKD", texto)
    semacento = "".join(c for c in semacento if not unicodedata.combining(c))
    return re.sub(r"[^\w\s-]", "", semacento).strip().lower()


def e_excecao_medica(texto: str) -> bool:
    """True se o trecho for termo clinico, nao nome de pessoa.

    Confere a expressao inteira e cada palavra: o spaCy costuma devolver
    "mal de Chagas" ou so "Chagas", e os dois precisam ser poupados.
    """
    normalizado = _normalizar_nome(texto)
    if not normalizado:
        return True
    if normalizado in EXCECOES_MEDICAS:
        return True
    palavras = [p for p in re.split(r"[\s-]+", normalizado) if p]
    # "doenca de Crohn" -> poupa, porque "crohn" esta na lista.
    return any(palavra in EXCECOES_MEDICAS for palavra in palavras)


# ---------------------------------------------------------------------------
# Carregamento preguicoso do spaCy
# ---------------------------------------------------------------------------

_MODELO = "pt_core_news_lg"
_nlp_cache: Any = None


def carregar_nlp() -> Any:
    """Carrega `pt_core_news_lg` uma unica vez; None se indisponivel.

    Devolver None em vez de estourar e proposital: sem o modelo a camada 1
    (regex) continua protegendo CPF/telefone/e-mail. Degradar e melhor do
    que derrubar o atendimento - e o log avisa o operador.
    """
    global _nlp_cache
    if _nlp_cache is not None:
        return _nlp_cache if _nlp_cache is not False else None
    try:
        import spacy

        _nlp_cache = spacy.load(_MODELO)
    except Exception as erro:  # modelo ausente, spaCy ausente, etc.
        print(f"[ANONIMIZACAO] NER indisponivel ({erro}); seguindo so com regex.")
        _nlp_cache = False
        return None
    return _nlp_cache


def _ocorrencias_do_cadastro(
    texto: str, nomes: Iterable[str]
) -> list[tuple[int, int, str, str]]:
    """Casamento exato dos nomes conhecidos, ignorando caixa e acento.

    Nomes mais longos primeiro: "Maria Souza Lima" deve vencer "Maria",
    senao sobraria " Souza Lima" no texto.
    """
    achados: list[tuple[int, int, str, str]] = []
    unicos = {n.strip() for n in nomes if n and n.strip()}

    for nome in sorted(unicos, key=len, reverse=True):
        # Nome com uma letra so geraria ruido; e `\b` nao ajuda com acento.
        if len(nome) < 3 or e_excecao_medica(nome):
            continue
        padrao = re.compile(
            r"(?<!\w)" + r"\s+".join(re.escape(parte) for parte in nome.split()) + r"(?!\w)",
            re.IGNORECASE,
        )
        for casamento in padrao.finditer(texto):
            achados.append((casamento.start(), casamento.end(), TIPO_PESSOA, casamento.group(0)))
    return achados


def _ocorrencias_do_ner(texto: str, nlp: Any) -> list[tuple[int, int, str, str]]:
    achados: list[tuple[int, int, str, str]] = []

    # Tokens criados pela camada de regex (CPF, telefone, data etc.)
    # ja estao protegidos e nao podem ser reinterpretados pelo NER.
    tokens_protegidos = [
        casamento.span()
        for casamento in _REGEX_TOKEN.finditer(texto)
    ]

    documento = nlp(texto)

    for entidade in getattr(documento, "ents", []):
        tipo = _ROTULOS.get(getattr(entidade, "label_", ""))
        if tipo is None:
            continue

        trecho = entidade.text

        # Rotulos de campos da estrutura clinica nao sao PII.
        # O NER pode classifica-los incorretamente como LOC.
        if _normalizar_nome(trecho) in ROTULOS_ESTRUTURAIS:
            continue

        if e_excecao_medica(trecho):
            continue

        inicio = getattr(entidade, "start_char", None)
        fim = getattr(entidade, "end_char", None)

        if inicio is None or fim is None:
            # Stub de teste sem offsets: localiza pela primeira ocorrencia.
            posicao = texto.find(trecho)
            if posicao < 0:
                continue
            inicio, fim = posicao, posicao + len(trecho)

        # Se a entidade do NER estiver dentro de um token que ja foi
        # produzido pelo regex, ignoramos a entidade.
        # Exemplo: [TELEFONE_1] nao pode virar [[LOCAL_1]].
        dentro_de_token = any(
            inicio < token_fim and token_inicio < fim
            for token_inicio, token_fim in tokens_protegidos
        )
        if dentro_de_token:
            continue

        achados.append((inicio, fim, tipo, trecho))

    return achados


def anonimizar_ner(
    texto: str,
    mapa: MapaAnonimizacao | None = None,
    nomes_conhecidos: Sequence[str] = (),
    nlp: Any = None,
    carregador: Callable[[], Any] = carregar_nlp,
) -> Resultado:
    """Camada 2: troca nomes de pessoa e lugar por tokens.

    `nomes_conhecidos` vem do cadastro de pacientes (B26). `nlp` permite
    injetar um modelo nos testes; sem ele, o carregador preguicoso decide.
    """
    mapa = mapa if mapa is not None else MapaAnonimizacao()
    if not texto:
        return Resultado(texto=texto or "", mapa=mapa)

    # Cadastro primeiro: tem prioridade sobre o palpite do NER.
    ocorrencias = _ocorrencias_do_cadastro(texto, nomes_conhecidos)

    modelo = nlp if nlp is not None else carregador()
    if modelo is not None:
        ocorrencias.extend(_ocorrencias_do_ner(texto, modelo))

    if not ocorrencias:
        return Resultado(texto=texto, mapa=mapa)

    # Remove sobreposicoes mantendo quem foi detectado primeiro (cadastro) e,
    # em empate, o trecho mais longo.
    ocorrencias.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    sem_colisao: list[tuple[int, int, str, str]] = []
    for ocorrencia in ocorrencias:
        inicio, fim = ocorrencia[0], ocorrencia[1]
        if any(inicio < f and i < fim for i, f, _, _ in sem_colisao):
            continue
        sem_colisao.append(ocorrencia)

    partes: list[str] = []
    cursor = 0
    for inicio, fim, tipo, trecho in sem_colisao:
        partes.append(texto[cursor:inicio])
        partes.append(mapa.token_para(tipo, trecho))
        cursor = fim
    partes.append(texto[cursor:])

    return Resultado(texto="".join(partes), mapa=mapa)
