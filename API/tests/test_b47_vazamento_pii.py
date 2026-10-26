"""B47 - teste de vazamento de PII textual (US016-CA003).

Percorre os 20 casos sintéticos da B45 (eval/cases/caso-NN.json) e, para
cada um, exercita as rotas /api/consultations/<id>/soap e /api/chat com o
envio ao Gemini interceptado por mock. Se qualquer PII plantada no caso
aparecer no payload que SERIA enviado, o teste falha.

Modo determinístico
-------------------
O CI não instala spaCy (requirements-dev.txt é enxuto de propósito), mas
a máquina de desenvolvimento pode ter o modelo pt_core_news_lg. Para que
o resultado não dependa do ambiente, os testes bloqueantes aplicam a
fixture `ner_desligado`, que seta `_nlp_cache = False` em
backend.anonimizacao.ner. Com isso, o NER nunca carrega: só a camada 1
(regex) e a lista de nomes do cadastro atuam, igual no CI.

Lacunas conhecidas
------------------
O dicionário LACUNAS_CONHECIDAS (abaixo) começa vazio. Na Fase 3, ele é
preenchido com os pares (id_caso, valor_literal) que o anonimizador
deixa passar de propósito (ex.: endereço completo, data por extenso com
dia escrito por palavra, telefone por extenso). Cada entrada tem um
motivo curto. O teste principal EXCLUI esses valores da checagem
bloqueante; um teste xfail(strict=True) por entrada verifica que o valor
continua vazando (e derruba a suíte quando o anonimizador for corrigido,
avisando para remover a entrada).

Rotas cobertas
--------------
- POST /api/consultations/<id>/soap -> backend.llm.chat.gerar_resposta_unica
- POST /api/chat                   -> backend.llm.chat.send_message

Fora de escopo
--------------
- Áudio enviado ao Gemini para transcrição (B31): outro fluxo.
- Rotas de recomendações, PDF e pep-import.
- Nomes de terceiros (mãe em caso-19/20) sem spaCy: cobertos num teste
  separado, com skip claro quando o modelo não está instalado.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest

from backend.anonimizacao import anonimizar
from backend.anonimizacao import ner as ner_mod
from backend.anonimizacao.padroes import valida_cpf
from ids import TEST_USER_ID
from repositories import (
    ConsultaRepository,
    PacienteRepository,
    TranscricaoRepository,
    sessao,
)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

CASES_DIR = Path(__file__).resolve().parent.parent / "eval" / "cases"

# Paciente da consulta quando o caso tem mais de uma pessoa com PII. O
# padrão (primeiro nome de pii_plantada.nome_completo) falharia nos casos
# de puericultura: a primeira da lista é a mãe, mas a consulta é do filho.
PACIENTES_POR_EXCECAO = {
    "caso-19": "Thiago dos Santos Pereira",
    "caso-20": "Lucas Alves de Lima",
}

# Lacunas conhecidas do anonimizador: (id_caso, valor_literal) -> motivo.
# Preenchido após a descoberta empírica da Fase 3 (rodada com NER off).
# Cada entrada é um valor que o anonimizador deixa passar por falta de
# padrão em padroes.py. O teste A (bloqueante) filtra esses pares; um
# teste xfail(strict=True) separado verifica que continuam vazando, para
# derrubar a suíte quando alguém corrigir o anonimizador.
LACUNAS_CONHECIDAS: dict[tuple[str, str], str] = {
    # --- data por extenso com dia escrito por palavra (9 casos) ---
    # O regex da DATA exige dia numérico; "quinze de março" escapa.
    ("caso-01", "quinze de março de 1985"):
        "data por extenso com dia por palavra",
    ("caso-02", "Dez de julho de 1998"):
        "data por extenso com dia por palavra",
    ("caso-04", "Cinco de maio de 2004"):
        "data por extenso com dia por palavra",
    ("caso-06", "Dezenove de novembro de 1980"):
        "data por extenso com dia por palavra",
    ("caso-09", "Vinte e oito de fevereiro de 1968"):
        "data por extenso com dia por palavra",
    ("caso-11", "Vinte e três de abril de 1995"):
        "data por extenso com dia por palavra",
    ("caso-13", "Doze de janeiro de 1962"):
        "data por extenso com dia por palavra",
    ("caso-15", "Vinte e nove de junho de 1984"):
        "data por extenso com dia por palavra",
    ("caso-17", "Primeiro de dezembro de 1988"):
        "data por extenso com dia por palavra",
    # --- telefone por extenso (6 casos) ---
    # O regex de TELEFONE exige dígitos; "Oitenta e um, ..." escapa.
    ("caso-02", "Oitenta e um, nove nove oito sete sete, seis cinco quatro três"):
        "telefone por extenso sem padrão em padroes.py",
    ("caso-06", "Oitenta e um, nove seis seis seis cinco, quatro três dois um"):
        "telefone por extenso sem padrão em padroes.py",
    ("caso-09", "Oitenta e um, nove quatro quatro quatro três, dois um zero nove"):
        "telefone por extenso sem padrão em padroes.py",
    ("caso-13", "Oitenta e um, nove oito sete sete sete, seis cinco quatro três"):
        "telefone por extenso sem padrão em padroes.py",
    ("caso-14", "Oitenta e um, nove nove oito oito oito, um dois três quatro"):
        "telefone por extenso sem padrão em padroes.py",
    ("caso-17", "Oitenta e um, nove nove nove nove nove, um um um um"):
        "telefone por extenso sem padrão em padroes.py",
    # --- endereço (logradouro+número) sem padrão de endereço (20 casos) ---
    # padroes.py cobre só CEP; o resto do endereço passa intacto.
    ("caso-01", "Rua das Flores, 123, Boa Vista, Recife-PE, CEP 50050-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-02", "Avenida Boa Viagem, 456, Apto 301, Boa Viagem, Recife-PE, CEP 51020-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-03", "Rua da Aurora, 789, Santo Amaro, Recife-PE, CEP 50050-901"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-04", "Rua Setúbal, 1000, Boa Viagem, Recife-PE, CEP 51030-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-05", "Rua do Futuro, 200, Graças, Recife-PE, CEP 52050-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-06", "Rua dos Coelhos, 321, Ilha do Leite, Recife-PE, CEP 50070-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-07", "Rua da Guia, 555, Bairro do Recife, Recife-PE, CEP 50030-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-08", "Rua do Príncipe, 800, Santo Antônio, Recife-PE, CEP 50050-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-09", "Rua da Matriz, 45, Casa Amarela, Recife-PE, CEP 52070-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-10", "Rua das Pernambucanas, 300, Graças, Recife-PE, CEP 52011-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-11", "Rua do Sossego, 77, Boa Vista, Recife-PE, CEP 50050-090"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-12", "Rua da Concórdia, 250, São José, Recife-PE, CEP 50050-100"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-13", "Rua do Hospício, 400, Boa Vista, Recife-PE, CEP 50050-050"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-14", "Rua do Sol, 150, Boa Vista, Recife-PE, CEP 50050-030"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-15", "Rua do Imperador, 500, Santo Antônio, Recife-PE, CEP 50010-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-16", "Rua da Penha, 200, São José, Recife-PE, CEP 50020-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-17", "Rua do Lima, 300, Santo Amaro, Recife-PE, CEP 50050-080"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-18", "Rua da Hora, 180, Espinheiro, Recife-PE, CEP 52020-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-19", "Rua da Alegria, 90, Casa Forte, Recife-PE, CEP 52060-000"):
        "logradouro+número sem padrão de endereço em padroes.py",
    ("caso-20", "Rua do Futuro, 900, Graças, Recife-PE, CEP 52050-100"):
        "logradouro+número sem padrão de endereço em padroes.py",
}

# Nomes de terceiros (mãe nos casos de puericultura). Esses nomes só são
# anonimizados pela camada NER (spaCy), que está desligada no modo
# determinístico. Por isso ficam fora da checagem bloqueante — a estrutura
# separada permite um teste específico com NER ligado.
NOMES_DEPENDENTES_DE_NER: frozenset[tuple[str, str]] = frozenset({
    ("caso-19", "Aline Cristina dos Santos Pereira"),
    ("caso-20", "Renata Alves de Lima"),
})

# Regex de token de anonimização. Aceita underscore no meio ([PACIENTE_1])
# e dígitos no fim ([CPF_1], [CPF_12]).
TOKEN_REGEX = re.compile(r"\[[A-Z_]+\d*\]")

# Padrões genéricos que NÃO podem aparecer no payload (mesma base do
# test_anonimizacao_rotas, B25/B26).
PADROES_GENERICOS = {
    "cpf_com_pontuacao": re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "cep_com_hifen": re.compile(r"\b\d{5}-\d{3}\b"),
    "data_numerica": re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"),
    "sequencia_11_digitos": re.compile(r"\b\d{11}\b"),
}

CATEGORIAS_COM_DIGITOS = frozenset({"cpf", "telefone", "cep"})


# ---------------------------------------------------------------------------
# Helpers de carregamento
# ---------------------------------------------------------------------------

def _carregar_casos() -> list[Path]:
    if not CASES_DIR.is_dir():
        pytest.fail(
            f"Pasta de casos não encontrada: {CASES_DIR}. "
            f"Esperados 20 arquivos caso-NN.json da B45."
        )
    casos = sorted(CASES_DIR.glob("caso-[0-9][0-9].json"))
    if len(casos) != 20:
        pytest.fail(
            f"Esperados exatamente 20 casos em {CASES_DIR}, "
            f"encontrados {len(casos)}: {[c.name for c in casos]}"
        )
    return casos


def _carregar_caso(caminho: Path) -> dict:
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


CASOS = _carregar_casos()
IDS_PARAM = lambda p: p.stem  # noqa: E731


# ---------------------------------------------------------------------------
# Helpers de preparação
# ---------------------------------------------------------------------------

def _escolher_nome_do_paciente(caso: dict) -> str:
    """Nome do paciente da consulta.

    Padrão: primeiro nome de pii_plantada.nome_completo. Exceção: casos
    19 e 20, onde a consulta é do filho (o primeiro da lista é a mãe).
    A função VALIDA que o nome escolhido está na lista, para falhar cedo
    se o caso for editado no futuro e a exceção deixar de fazer sentido.
    """
    nomes = caso["pii_plantada"]["nome_completo"]
    if caso["id"] in PACIENTES_POR_EXCECAO:
        nome = PACIENTES_POR_EXCECAO[caso["id"]]
        assert nome in nomes, (
            f"{caso['id']}: PACIENTES_POR_EXCECAO aponta para {nome!r}, "
            f"mas esse nome não está em pii_plantada.nome_completo: {nomes}"
        )
        return nome
    return nomes[0]


def _preparar_caso_na_api(caso: dict) -> tuple[str, str]:
    """Cadastra paciente + consulta e semeia a transcrição do caso.

    Devolve (patient_id, consultation_id). Não usa o client Flask: a
    semeadura é feita direto nos repositórios, como no test_b40.
    """
    s = sessao.obter_sessao()
    nome = _escolher_nome_do_paciente(caso)
    pid = PacienteRepository(s).criar(nome=nome, medico_id=TEST_USER_ID)["id"]
    cid = ConsultaRepository(s).criar(pid, "Consulta B47")
    TranscricaoRepository(s).adicionar(
        pid, cid, texto=caso["transcricao"], duracao_s=60,
    )
    return pid, cid


# ---------------------------------------------------------------------------
# Helpers de detecção
# ---------------------------------------------------------------------------

def _normalizar_texto(txt: str) -> str:
    """Remove acentos, aplica casefold e colapsa espaços."""
    decomposto = unicodedata.normalize("NFKD", txt)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().casefold()


def _regex_digitos_tolerante(valor: str) -> re.Pattern[str] | None:
    """Regex que casa os dígitos de `valor` com separadores opcionais entre eles.

    Ex.: '123.456.789-09' vira `1\\D*2\\D*3...0\\D*9`. Casa tanto o
    valor literal quanto o valor sem pontuação, e com pontos/traços/
    espaços/parênteses entre os dígitos.
    """
    digitos = re.sub(r"\D", "", valor)
    if not digitos:
        return None
    return re.compile(r"\D*".join(re.escape(d) for d in digitos))


def _logradouro_numero(endereco: str) -> str | None:
    """Extrai 'logradouro, número' dos dois primeiros pedaços do endereço.

    Ex.: 'Rua das Flores, 123, Boa Vista, Recife-PE, CEP 50050-000'
    -> 'Rua das Flores, 123'. Devolve None se não houver ao menos 2 pedaços.
    """
    partes = [p.strip() for p in endereco.split(",") if p.strip()]
    if len(partes) < 2:
        return None
    return f"{partes[0]}, {partes[1]}"


def _contem_valor(payload: str, valor: str, categoria: str) -> bool:
    """Verifica se `valor` aparece no payload, com tolerância por categoria.

    - Texto livre (nome, email, etc.): comparação normalizada (sem acento,
      casefold).
    - cpf/telefone/cep: regex tolerante a separadores entre dígitos.
    - endereco: só 'logradouro, número', normalizado (Bairro/cidade não
      bloqueiam; só o par rua+número é PII forte).
    """
    payload_norm = _normalizar_texto(payload)
    valor_norm = _normalizar_texto(valor)

    if categoria == "endereco":
        chave = _logradouro_numero(valor)
        if chave is None:
            return False
        return _normalizar_texto(chave) in payload_norm

    if categoria in CATEGORIAS_COM_DIGITOS:
        digitos = re.sub(r"\D", "", valor)
        if digitos:
            padrao = _regex_digitos_tolerante(valor)
            if padrao is None:
                return False
            return padrao.search(payload) is not None
        # Valor por extenso (sem dígitos): fallback para comparação
        # literal normalizada com word boundary. Sem isso, telefone
        # por extenso ("Oitenta e um, ...") nunca seria detectado —
        # falso negativo que esconderia vazamento real.
        padrao_livre = re.compile(
            r"(?<!\w)" + re.escape(valor_norm) + r"(?!\w)"
        )
        return padrao_livre.search(payload_norm) is not None

    # Texto livre: exigir fronteira de palavra, para não confundir
    # substring com ocorrência real (ex.: "Maria" dentro de "primária",
    # que após a normalização de acentos vira "primaria").
    padrao_livre = re.compile(
        r"(?<!\w)" + re.escape(valor_norm) + r"(?!\w)"
    )
    return padrao_livre.search(payload_norm) is not None


def _detectar_vazamentos(
    caso: dict,
    payload: str,
    *,
    ignorar_lacunas: bool,
    ignorar_nomes_de_terceiros: bool = True,
) -> list[tuple[str, str]]:
    """Lista de (categoria, valor) da PII plantada que apareceu no payload.

    - `ignorar_lacunas`: pula pares registrados em LACUNAS_CONHECIDAS.
      Usado pelo teste A bloqueante para não falhar em lacunas conhecidas.
    - `ignorar_nomes_de_terceiros`: pula nomes em NOMES_DEPENDENTES_DE_NER
      (mãe nos casos de puericultura). Só são anonimizados com NER ligado,
      então ficam fora do modo determinístico. As OUTRAS categorias da
      mesma pessoa (CPF, telefone, etc.) continuam sendo checadas.
    """
    vazamentos: list[tuple[str, str]] = []
    pii = caso["pii_plantada"]
    for categoria, valores in pii.items():
        for valor in valores:
            if ignorar_lacunas and (caso["id"], valor) in LACUNAS_CONHECIDAS:
                continue
            if (
                ignorar_nomes_de_terceiros
                and categoria == "nome_completo"
                and (caso["id"], valor) in NOMES_DEPENDENTES_DE_NER
            ):
                continue
            if _contem_valor(payload, valor, categoria):
                vazamentos.append((categoria, valor))
    return vazamentos


def _detectar_padroes_genericos(payload: str) -> list[tuple[str, str]]:
    """Aplica os padrões genéricos ao payload e devolve (nome, trecho)."""
    achados: list[tuple[str, str]] = []
    for nome, padrao in PADROES_GENERICOS.items():
        for match in padrao.finditer(payload):
            trecho = match.group(0)
            if nome == "sequencia_11_digitos" and not valida_cpf(trecho):
                # 11 dígitos que NÃO passam em DV: não é CPF, é outra coisa.
                continue
            achados.append((nome, trecho))
    return achados


def _verificar_sanidade(payload: str, caso: dict) -> None:
    """Confere que a anonimização não apagou o conteúdo clínico.

    - Se o caso tem CPF, o payload tem que ter pelo menos um token.
    - O payload não pode ser menor que 50% do material original.
    """
    if "cpf" in caso["pii_plantada"] and caso["pii_plantada"]["cpf"]:
        assert TOKEN_REGEX.search(payload), (
            f"{caso['id']}: nenhum token de anonimização no payload, "
            f"mas o caso tem CPF. A anonimização pode não ter rodado."
        )
    tamanho_original = len(caso["transcricao"])
    # Tolera o cabeçalho das seções (## Transcrição, etc.), mas não
    # admite colapso total do material.
    assert len(payload) >= tamanho_original * 0.5, (
        f"{caso['id']}: payload com {len(payload)} caracteres para "
        f"transcrição de {tamanho_original}. Anonimização pode ter "
        f"apagado o conteúdo clínico."
    )


# ---------------------------------------------------------------------------
# Mock do Gemini
# ---------------------------------------------------------------------------

_SOAP_VALIDO = {
    "subjetivo": "Paciente relata queixa.",
    "objetivo": "Exame físico sem alterações relevantes.",
    "avaliacao": "Hipótese diagnóstica a confirmar.",
    "plano": "Conduta e retorno conforme evolução.",
    "hipoteses": [{"descricao": "Hipótese", "cid10": "R00", "confianca": "baixa"}],
    "alertas": [],
    "pendencias": ["Reavaliar em retorno"],
}


class _ModeloFalsoSOAP:
    """Captura (instrucao, conteudo) de cada chamada e devolve SOAP fixo."""

    def __init__(self) -> None:
        self.chamadas: list[dict] = []

    def __call__(self, instrucao, conteudo, schema=None):
        self.chamadas.append({"instrucao": instrucao, "conteudo": conteudo})
        return json.dumps(_SOAP_VALIDO)


class _ModeloFalsoChat:
    """Captura message_text de cada chamada e devolve resposta fixa."""

    def __init__(self) -> None:
        self.chamadas: list[dict] = []

    def __call__(self, patient_id, consultation_id, message_text):
        self.chamadas.append({"message_text": message_text})
        return "Resposta simulada da IA."


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ner_desligado(monkeypatch):
    """Neutraliza a camada NER para resultado determinístico (CI == local)."""
    monkeypatch.setattr(ner_mod, "_nlp_cache", False)


@pytest.fixture()
def cofre_aberto(monkeypatch):
    """Cofre aberto: permite persistir o mapa de anonimização da consulta."""
    import server
    from backend.anonimizacao.cripto import criar_cofre

    aberto = criar_cofre("senha-de-teste-b47")[0]
    monkeypatch.setattr(server, "_cofre_atual", lambda: aberto)
    return aberto


@pytest.fixture()
def payloads_soap(monkeypatch):
    import server

    falso = _ModeloFalsoSOAP()
    monkeypatch.setattr(server.chat_ia, "gerar_resposta_unica", falso)
    return falso


@pytest.fixture()
def payloads_chat(monkeypatch):
    import server

    falso = _ModeloFalsoChat()
    monkeypatch.setattr(server.chat_ia, "send_message", falso)
    return falso


# ---------------------------------------------------------------------------
# Testes-canário (provam que o verificador não está cego)
# ---------------------------------------------------------------------------

@pytest.mark.leak
def test_canario_texto_cru_acusa_vazamento():
    """Se o texto cru (não anonimizado) for passado, o verificador DEVE acusar.

    Sem isso, não temos como confiar que um "passou" no teste principal
    significa que o anonimizador funcionou.
    """
    caso = _carregar_caso(CASOS[0])  # caso-01
    texto_cru = caso["transcricao"]

    vazamentos = _detectar_vazamentos(
        caso, texto_cru, ignorar_lacunas=False,
    )
    assert vazamentos, (
        f"{caso['id']}: verificador não detectou nenhum vazamento no "
        f"texto cru. O teste está cego."
    )


@pytest.mark.leak
def test_canario_texto_anonimizado_passa(ner_desligado):
    """Texto 100% coberto pela anonimização não deve acusar falso positivo.

    Usa um texto sintético mínimo, com categorias que a camada 1 (regex)
    e a lista de nomes do cadastro cobrem deterministicamente: nome,
    CPF, telefone, e-mail e CEP. NÃO usa endereço nem data por extenso,
    porque essas duas categorias têm lacunas conhecidas no anonimizador
    (documentadas em LACUNAS_CONHECIDAS quando preenchido). O objetivo
    deste canário é só provar que o detector não dá falso positivo em
    texto limpo — as lacunas reais aparecem nos testes A/B por caso.
    """
    texto = (
        "Maria Souza informou CPF 123.456.789-09, "
        "telefone (81) 99999-1234, e-mail maria.souza@email.com, "
        "CEP 50050-000."
    )
    caso_sintetico = {
        "id": "sintetico-canario",
        "transcricao": texto,
        "pii_plantada": {
            "nome_completo": ["Maria Souza"],
            "cpf": ["123.456.789-09"],
            "telefone": ["(81) 99999-1234"],
            "email": ["maria.souza@email.com"],
            "cep": ["50050-000"],
        },
    }
    resultado = anonimizar(texto, nomes_conhecidos=["Maria Souza"])
    texto_anon = resultado.texto

    vazamentos = _detectar_vazamentos(
        caso_sintetico, texto_anon, ignorar_lacunas=True,
    )
    assert not vazamentos, (
        f"Texto anonimizado acusou vazamento: {vazamentos}. "
        f"O anonimizador deveria cobrir todas as categorias deste canário."
    )
    assert TOKEN_REGEX.search(texto_anon), (
        "Texto anonimizado não tem nenhum token. Anonimização pode não ter rodado."
    )
    assert len(texto_anon) >= len(texto) * 0.5, (
        f"Texto anonimizado é muito menor que o original "
        f"({len(texto_anon)} vs {len(texto)}). Anonimização apagou conteúdo."
    )


@pytest.mark.leak
def test_canario_telefone_por_extenso_acusa_vazamento():
    """Prova que telefone por extenso (sem dígitos) é detectado no texto cru.

    Regressão real (corrigida na B47): a regex de dígitos retornava None
    para valores como "Oitenta e um, nove nove...", e o verificador
    silenciosamente ignorava esses valores — o telefone por extenso
    vazava nos casos 02, 06, 13, 14 e 17 sem que o teste A acusasse.
    Com o fallback de comparação literal normalizada, este canário
    garante que a regressão não volta.
    """
    caso = _carregar_caso(CASES_DIR / "caso-02.json")
    telefones_por_extenso = [
        t for t in caso["pii_plantada"].get("telefone", [])
        if not re.search(r"\d", t)
    ]
    assert telefones_por_extenso, (
        "caso-02 não tem telefone por extenso; o canário perdeu o sentido."
    )

    vazamentos = _detectar_vazamentos(
        caso, caso["transcricao"], ignorar_lacunas=False,
    )
    for valor in telefones_por_extenso:
        assert ("telefone", valor) in vazamentos, (
            f"Telefone por extenso {valor!r} NÃO foi detectado no texto cru. "
            f"Verificador tem falso negativo para valores sem dígitos."
        )


# ---------------------------------------------------------------------------
# Teste A — rota /soap (bloqueante, parametrizado ×20)
# ---------------------------------------------------------------------------

@pytest.mark.leak
@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_rota_soap_nao_vaza_pii(
    caminho,
    client,
    auth_headers,
    ner_desligado,
    cofre_aberto,
    payloads_soap,
):
    """Cada caso da B45 passa pela rota /soap; nenhum valor de pii_plantada
    pode aparecer no payload que SERIA enviado ao Gemini.

    Modo determinístico: NER desligado (ner_desligado). Lacunas conhecidas
    são filtradas (LACUNAS_CONHECIDAS), então o teste só falha em valores
    que NÃO são lacunas documentadas. Quando LACUNAS_CONHECIDAS estiver
    vazio (estado de descoberta), qualquer valor que aparecer é candidato
    a lacuna real — precisa de aprovação do time antes de registrar.
    """
    caso = _carregar_caso(caminho)
    pid, cid = _preparar_caso_na_api(caso)

    resposta = client.post(
        f"/api/consultations/{cid}/soap",
        headers=auth_headers("medico"),
    )
    assert resposta.status_code == 201, (
        f"{caso['id']}: POST /soap devolveu status {resposta.status_code}. "
        f"Body: {resposta.get_data(as_text=True)[:300]}"
    )

    assert payloads_soap.chamadas, (
        f"{caso['id']}: nenhuma chamada ao Gemini foi capturada. "
        f"A rota /soap não chegou ao gerador."
    )

    # Concatena todas as chamadas (se houver retry, todas são inspecionadas).
    payload = "\n\n".join(
        f"{chamada['instrucao']}\n\n{chamada['conteudo']}"
        for chamada in payloads_soap.chamadas
    )

    vazamentos = _detectar_vazamentos(caso, payload, ignorar_lacunas=True)
    assert not vazamentos, (
        f"{caso['id']}: PII vazou na rota /soap: {vazamentos}. "
        f"Se algum desses valores for lacuna conhecida do anonimizador, "
        f"registre em LACUNAS_CONHECIDAS (precisa de aprovação do time)."
    )

    padroes = _detectar_padroes_genericos(payload)
    assert not padroes, (
        f"{caso['id']}: padrão genérico de PII no payload: {padroes}."
    )

    _verificar_sanidade(payload, caso)


# ---------------------------------------------------------------------------
# Teste B — rota /api/chat (bloqueante, parametrizado ×20)
# ---------------------------------------------------------------------------

@pytest.mark.leak
@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_rota_chat_nao_vaza_pii(
    caminho,
    client,
    auth_headers,
    ner_desligado,
    cofre_aberto,
    payloads_chat,
):
    """Cada caso da B45 passa pela rota /api/chat; nenhum valor de
    pii_plantada pode aparecer no texto enviado ao Gemini.

    Mesma política do Teste A: NER desligado, lacunas conhecidas
    filtradas, nomes de terceiros (mãe) fora da checagem determinística.
    A rota /api/chat anonimiza `message` antes de chamar send_message —
    este teste confirma que a anonimização está de fato no caminho.
    """
    caso = _carregar_caso(caminho)
    pid, cid = _preparar_caso_na_api(caso)

    resposta = client.post(
        "/api/chat",
        json={
            "message": caso["transcricao"],
            "patient_id": pid,
            "consultation_id": cid,
        },
        headers=auth_headers("medico"),
    )
    assert resposta.status_code == 200, (
        f"{caso['id']}: POST /api/chat devolveu status {resposta.status_code}. "
        f"Body: {resposta.get_data(as_text=True)[:300]}"
    )

    assert payloads_chat.chamadas, (
        f"{caso['id']}: nenhuma chamada ao Gemini foi capturada. "
        f"A rota /api/chat não chegou ao send_message."
    )

    # Se houver retry, todas as chamadas são inspecionadas.
    payload = "\n\n".join(
        chamada["message_text"] for chamada in payloads_chat.chamadas
    )

    vazamentos = _detectar_vazamentos(caso, payload, ignorar_lacunas=True)
    assert not vazamentos, (
        f"{caso['id']}: PII vazou na rota /api/chat: {vazamentos}. "
        f"Se algum desses valores for lacuna conhecida do anonimizador, "
        f"registre em LACUNAS_CONHECIDAS (precisa de aprovação do time)."
    )

    padroes = _detectar_padroes_genericos(payload)
    assert not padroes, (
        f"{caso['id']}: padrão genérico de PII no payload do chat: {padroes}."
    )

    _verificar_sanidade(payload, caso)


# ---------------------------------------------------------------------------
# Testes das lacunas conhecidas (xfail strict)
# ---------------------------------------------------------------------------

def _categoria_do_valor(caso: dict, valor: str) -> str:
    """Descobre em qual categoria de pii_plantada um valor está.

    Usado só pelos testes de lacuna, para chamar _contem_valor com a
    categoria certa. Falha se o valor não estiver em nenhuma (sinal de
    que LACUNAS_CONHECIDAS está fora de sincronia com os casos).
    """
    for categoria, valores in caso["pii_plantada"].items():
        if valor in valores:
            return categoria
    raise AssertionError(
        f"{caso['id']}: valor {valor!r} de LACUNAS_CONHECIDAS não está "
        f"em nenhuma categoria de pii_plantada."
    )


@pytest.mark.leak
@pytest.mark.skipif(
    not LACUNAS_CONHECIDAS,
    reason="sem lacunas registradas em LACUNAS_CONHECIDAS",
)
@pytest.mark.parametrize(
    "caso_id,valor",
    [
        pytest.param(cid, val, marks=pytest.mark.xfail(strict=True, reason=motivo))
        for (cid, val), motivo in LACUNAS_CONHECIDAS.items()
    ],
    ids=[
        f"{cid}-{i}"
        for i, (cid, _) in enumerate(LACUNAS_CONHECIDAS.keys())
    ],
)
def test_lacuna_conhecida_nao_vaza(
    caso_id,
    valor,
    client,
    auth_headers,
    ner_desligado,
    cofre_aberto,
    payloads_soap,
):
    """Confirma que a lacuna registrada AINDA vaza (xfail strict).

    Quando o anonimizador for corrigido, este teste vira XPASS e o
    strict=True derruba a suíte, avisando para remover a entrada de
    LACUNAS_CONHECIDAS. Assim o problema não fica escondido para sempre.
    """
    caso = _carregar_caso(CASES_DIR / f"{caso_id}.json")
    categoria = _categoria_do_valor(caso, valor)
    pid, cid = _preparar_caso_na_api(caso)

    resposta = client.post(
        f"/api/consultations/{cid}/soap",
        headers=auth_headers("medico"),
    )
    assert resposta.status_code == 201, (
        f"{caso_id}: POST /soap devolveu status {resposta.status_code}."
    )

    payload = "\n\n".join(
        f"{chamada['instrucao']}\n\n{chamada['conteudo']}"
        for chamada in payloads_soap.chamadas
    )

    vazou = _contem_valor(payload, valor, categoria)
    assert not vazou, (
        f"{caso_id}: o valor {valor!r} (categoria {categoria!r}) ainda vaza "
        f"(lacuna conhecida, xfail strict). Quando o anonimizador for "
        f"corrigido, este teste vai passar e o XPASS(strict) derruba a "
        f"suíte, avisando para remover a entrada de LACUNAS_CONHECIDAS."
    )


# ---------------------------------------------------------------------------
# Nome de terceiros (mãe) com NER ligado
# ---------------------------------------------------------------------------

@pytest.mark.leak
@pytest.mark.parametrize(
    "caso_id,nome_mae",
    sorted(NOMES_DEPENDENTES_DE_NER),
    ids=[f"{cid}" for cid, _ in sorted(NOMES_DEPENDENTES_DE_NER)],
)
def test_nome_de_terceiro_anonimizado_com_ner(
    caso_id,
    nome_mae,
    client,
    auth_headers,
    cofre_aberto,
    payloads_soap,
):
    """Com NER ligado, o nome da mãe (terceiro) deve ser anonimizado.

    Skip explícito quando spaCy ou o modelo pt_core_news_lg não estão
    disponíveis — o CI cai nesse caso, e o teste não bloqueia. Não usa a
    fixture ner_desligado: o objetivo é justamente exercitar o caminho
    com NER real, que é onde os nomes de terceiros dependem de spaCy.
    """
    spacy = pytest.importorskip(
        "spacy", reason="spaCy não instalado; NER indisponível neste ambiente"
    )
    try:
        spacy.load("pt_core_news_lg")
    except OSError as exc:
        pytest.skip(
            f"spaCy instalado mas modelo pt_core_news_lg ausente: {exc}"
        )

    caso = _carregar_caso(CASES_DIR / f"{caso_id}.json")
    pid, cid = _preparar_caso_na_api(caso)

    resposta = client.post(
        f"/api/consultations/{cid}/soap",
        headers=auth_headers("medico"),
    )
    assert resposta.status_code == 201, (
        f"{caso_id}: POST /soap devolveu status {resposta.status_code}."
    )

    payload = "\n\n".join(
        f"{chamada['instrucao']}\n\n{chamada['conteudo']}"
        for chamada in payloads_soap.chamadas
    )

    assert nome_mae not in payload, (
        f"{caso_id}: nome de terceiro {nome_mae!r} vazou mesmo com NER "
        f"ligado. O spaCy não classificou o nome como PER, ou a lista "
        f"do cadastro não o inclui. Registrar como lacuna real."
    )    