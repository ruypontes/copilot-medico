"""Testes de integridade dos 20 casos sintéticos da B45.

Este arquivo valida a FORMA dos casos em API/eval/cases/ — não o
comportamento do anonimizador nem a qualidade clínica do SOAP gerado.

Responsabilidades vizinhas (para não confundir escopo):
    - B45 (este arquivo): os 20 casos existem, têm estrutura correta,
      CID-10 único, PII coerente com o texto e CPF com DV válido.
    - B46: qualidade clínica do SOAP gerado contra o gabarito.
    - B47: vazamento de PII no payload enviado à IA externa.

Verificações cobertas (numeradas como na descrição da issue):
    0. A pasta eval/cases existe e tem exatamente 20 arquivos caso-NN.json,
       sem id duplicado.
    1. Cada arquivo é JSON válido (falha apontando qual arquivo).
    2. Cada caso tem EXATAMENTE as 7 chaves esperadas — nem a mais, nem a menos.
    3. O campo "id" bate com o nome do arquivo (caso-07.json -> "caso-07").
    4. gabarito_soap tem as 4 seções, todas strings não-vazias e com
       tamanho mínimo razoável (>= MIN_CHARS_SOAP).
    5. cid10_esperado tem exatamente 1 código, no formato CID-10.
    6. pendencias é uma lista não-vazia.
    7. pii_plantada é objeto não-vazio e TODOS os valores listados
       aparecem literalmente na transcricao (evita "PII fantasma").
    8. Cada CPF em pii_plantada.cpf tem dígito verificador válido,
       usando a MESMA função que o anonimizador usa
       (backend.anonimizacao.padroes.valida_cpf).
    9. Cada CEP em pii_plantada.cep tem 8 dígitos (formato apenas;
       não valida existência real nos Correios).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# Reaproveita a validação canônica do projeto (verificação 8).
# Se o nome/assinatura desta função mudar no futuro, o teste muda junto
# automaticamente, garantindo que o teste e o anonimizador concordem.
from backend.anonimizacao.padroes import valida_cpf


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

CASES_DIR = Path(__file__).resolve().parent.parent / "eval" / "cases"

CAMPOS_OBRIGATORIOS = frozenset(
    {
        "id",
        "queixa_principal",
        "transcricao",
        "gabarito_soap",
        "cid10_esperado",
        "pendencias",
        "pii_plantada",
    }
)

SECOES_SOAP = frozenset({"subjetivo", "objetivo", "avaliacao", "plano"})

# Mínimo de caracteres por seção SOAP. Valor baixo o bastante para
# não rejeitar nenhum caso legítimo e alto o bastante para pegar
# campos preenchidos com "" ou com uma única palavra.
MIN_CHARS_SOAP = 40

# Formato de CID-10: 1 letra maiúscula + 2 dígitos, opcionalmente
# com sufixo após ponto (ex.: R51, G44.2, Z00.1).
PADRAO_CID = re.compile(r"^[A-Z]\d{2}(\.\d{1,2})?$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _listar_casos() -> list[Path]:
    """Lista os arquivos caso-NN.json (dois dígitos) na pasta de casos."""
    if not CASES_DIR.is_dir():
        pytest.fail(
            f"A pasta de casos não existe: {CASES_DIR}. "
            f"Esperada a pasta 'API/eval/cases/' com os 20 arquivos caso-NN.json."
        )
    return sorted(CASES_DIR.glob("caso-[0-9][0-9].json"))


def _carregar(caminho: Path) -> dict:
    """Carrega um caso. Erro de sintaxe aponta o arquivo exato (verificação 1)."""
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"{caminho.name}: JSON inválido — {exc.msg} "
            f"(linha {exc.lineno}, coluna {exc.colno})"
        )


CASOS = _listar_casos()
IDS_PARAM = lambda p: p.stem  # noqa: E731 — id curto para o pytest


# ---------------------------------------------------------------------------
# Verificação 0 — a pasta como um todo
# ---------------------------------------------------------------------------

def test_existem_exatamente_20_arquivos_caso_nn():
    assert len(CASOS) == 20, (
        f"Esperados 20 arquivos 'caso-NN.json' em {CASES_DIR}, "
        f"encontrados {len(CASOS)}: {[c.name for c in CASOS]}"
    )


def test_pasta_de_casos_existe():
    assert CASES_DIR.is_dir(), f"A pasta {CASES_DIR} não existe."


def test_ids_sao_unicos_entre_arquivos():
    vistos: dict[str, str] = {}
    for caminho in CASOS:
        dados = _carregar(caminho)
        id_caso = dados.get("id")
        if id_caso in vistos:
            pytest.fail(
                f"id duplicado '{id_caso}': "
                f"aparece em {vistos[id_caso]} e {caminho.name}"
            )
        vistos[id_caso] = caminho.name


# ---------------------------------------------------------------------------
# Verificação 1 — cada arquivo é JSON válido
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_arquivo_e_json_valido(caminho):
    _carregar(caminho)  # levanta erro apontando o arquivo se inválido


# ---------------------------------------------------------------------------
# Verificação 2 — exatamente as 7 chaves esperadas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_chaves_exatas_nem_a_mais_nem_a_menos(caminho):
    dados = _carregar(caminho)
    chaves = set(dados.keys())

    faltando = CAMPOS_OBRIGATORIOS - chaves
    sobrando = chaves - CAMPOS_OBRIGATORIOS

    problemas: list[str] = []
    if faltando:
        problemas.append(f"faltando: {sorted(faltando)}")
    if sobrando:
        problemas.append(f"chaves não previstas: {sorted(sobrando)}")

    assert not problemas, f"{caminho.name}: " + "; ".join(problemas)


# ---------------------------------------------------------------------------
# Verificação 3 — id bate com nome do arquivo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_id_bate_com_nome_do_arquivo(caminho):
    dados = _carregar(caminho)
    assert dados.get("id") == caminho.stem, (
        f"{caminho.name}: campo 'id' é {dados.get('id')!r}, "
        f"mas o nome do arquivo implica {caminho.stem!r}"
    )


# ---------------------------------------------------------------------------
# Verificação 4 — gabarito_soap completo e com conteúdo de verdade
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_gabarito_soap_tem_exatamente_as_quatro_secoes(caminho):
    soap = _carregar(caminho)["gabarito_soap"]
    assert set(soap.keys()) == SECOES_SOAP, (
        f"{caminho.name}: gabarito_soap deve ter exatamente "
        f"{sorted(SECOES_SOAP)}; tem {sorted(soap.keys())}"
    )


@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_cada_secao_soap_tem_conteudo_nao_trivial(caminho):
    soap = _carregar(caminho)["gabarito_soap"]
    for secao in SECOES_SOAP:
        valor = soap[secao]
        assert isinstance(valor, str), (
            f"{caminho.name}: gabarito_soap['{secao}'] não é string "
            f"(é {type(valor).__name__})"
        )
        assert len(valor.strip()) >= MIN_CHARS_SOAP, (
            f"{caminho.name}: gabarito_soap['{secao}'] tem só "
            f"{len(valor.strip())} caracteres úteis "
            f"(mínimo {MIN_CHARS_SOAP})"
        )


# ---------------------------------------------------------------------------
# Verificação 5 — cid10_esperado (único e bem formado)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_cid10_unico_e_bem_formado(caminho):
    cids = _carregar(caminho)["cid10_esperado"]
    assert isinstance(cids, list), (
        f"{caminho.name}: cid10_esperado deve ser lista (é {type(cids).__name__})"
    )
    assert len(cids) == 1, (
        f"{caminho.name}: cid10_esperado deve ter exatamente 1 item; "
        f"tem {len(cids)}: {cids}"
    )
    cid = cids[0]
    assert isinstance(cid, str) and PADRAO_CID.match(cid), (
        f"{caminho.name}: CID {cid!r} não segue formato CID-10 "
        f"(ex.: R51, G44.2, Z00.1)"
    )


# ---------------------------------------------------------------------------
# Verificação 6 — pendencias não vazias
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_pendencias_lista_nao_vazia(caminho):
    pendencias = _carregar(caminho)["pendencias"]
    assert isinstance(pendencias, list), (
        f"{caminho.name}: pendencias deve ser lista "
        f"(é {type(pendencias).__name__})"
    )
    assert len(pendencias) > 0, f"{caminho.name}: pendencias está vazia"


# ---------------------------------------------------------------------------
# Verificação 7 — PII plantada é consistente com o texto
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_pii_plantada_e_objeto_nao_vazio(caminho):
    pii = _carregar(caminho)["pii_plantada"]
    assert isinstance(pii, dict), (
        f"{caminho.name}: pii_plantada deve ser objeto (é {type(pii).__name__})"
    )
    assert len(pii) > 0, f"{caminho.name}: pii_plantada está vazio"


@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_toda_pii_listada_aparece_na_transcricao(caminho):
    dados = _carregar(caminho)
    transcricao = dados["transcricao"]
    pii = dados["pii_plantada"]

    problemas: list[str] = []
    for categoria, valores in pii.items():
        if not isinstance(valores, list):
            problemas.append(
                f"pii_plantada['{categoria}'] deveria ser lista, "
                f"é {type(valores).__name__}"
            )
            continue
        for valor in valores:
            if valor not in transcricao:
                problemas.append(
                    f"pii_plantada['{categoria}'] contém {valor!r}, "
                    f"mas esse valor NÃO aparece na transcricao"
                )

    assert not problemas, f"{caminho.name}:\n  - " + "\n  - ".join(problemas)


# ---------------------------------------------------------------------------
# Verificação 8 — CPF com DV válido (reaproveita valida_cpf do projeto)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_cpfs_tem_digito_verificador_valido(caminho):
    cpfs = _carregar(caminho)["pii_plantada"].get("cpf", [])
    for cpf in cpfs:
        assert valida_cpf(cpf), (
            f"{caminho.name}: CPF {cpf!r} tem dígito verificador inválido "
            f"segundo backend.anonimizacao.padroes.valida_cpf — "
            f"o regex do anonimizador não vai detectá-lo e o teste da B47 "
            f"não estará testando CPF de verdade"
        )


# ---------------------------------------------------------------------------
# Verificação 9 — CEP no formato (8 dígitos, traço ignorado)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho", CASOS, ids=IDS_PARAM)
def test_ceps_tem_oito_digitos(caminho):
    ceps = _carregar(caminho)["pii_plantada"].get("cep", [])
    for cep in ceps:
        digitos = re.sub(r"\D", "", cep)
        assert len(digitos) == 8, (
            f"{caminho.name}: CEP {cep!r} tem {len(digitos)} dígitos "
            f"(esperado 8, ignorando traço)"
        )
        