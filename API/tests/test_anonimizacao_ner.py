"""Camada NER da anonimizacao (B26 / US016-CA001, ADR-03).

O spaCy e injetado como stub: carregar `pt_core_news_lg` (~600 MB) no CI
anularia o ganho do B13. O que importa testar aqui e a LOGICA em volta do
NER - prioridade do cadastro, excecoes medicas, resolucao de sobreposicao -
e nao a qualidade do modelo, que e responsabilidade do spaCy.
"""
from __future__ import annotations

import pytest

from backend.anonimizacao import (
    MapaAnonimizacao,
    TIPO_LOCAL,
    TIPO_PESSOA,
    anonimizar,
    anonimizar_ner,
    e_excecao_medica,
)


# ---------------------------------------------------------------------------
# Stub do spaCy
# ---------------------------------------------------------------------------

class _Entidade:
    def __init__(self, texto: str, rotulo: str, inicio: int, fim: int):
        self.text = texto
        self.label_ = rotulo
        self.start_char = inicio
        self.end_char = fim


class _Documento:
    def __init__(self, ents):
        self.ents = ents


def nlp_falso(*termos: tuple[str, str]):
    """Modelo que marca os termos informados sempre que aparecerem."""

    def _nlp(texto: str):
        achados = []
        for termo, rotulo in termos:
            inicio = 0
            while True:
                posicao = texto.find(termo, inicio)
                if posicao < 0:
                    break
                achados.append(_Entidade(termo, rotulo, posicao, posicao + len(termo)))
                inicio = posicao + len(termo)
        return _Documento(achados)

    return _nlp


# ---------------------------------------------------------------------------
# Nomes vindos do cadastro
# ---------------------------------------------------------------------------

def test_nome_do_cadastro_vira_token_sem_depender_do_ner():
    """A fonte mais confiavel e o proprio cadastro, nao o palpite do modelo."""
    resultado = anonimizar_ner(
        "Maria Souza compareceu a consulta.",
        nomes_conhecidos=["Maria Souza"],
        nlp=nlp_falso(),
    )

    assert "Maria Souza" not in resultado.texto
    assert f"[{TIPO_PESSOA}_1]" in resultado.texto


def test_nome_do_cadastro_casa_ignorando_caixa_e_espacos():
    resultado = anonimizar_ner(
        "Atendi MARIA  SOUZA hoje.",
        nomes_conhecidos=["Maria Souza"],
        nlp=nlp_falso(),
    )

    assert "MARIA" not in resultado.texto
    assert f"[{TIPO_PESSOA}_1]" in resultado.texto


def test_nome_mais_longo_vence_o_mais_curto():
    """Com "Maria" e "Maria Souza Lima" no cadastro, nao pode sobrar sobra."""
    resultado = anonimizar_ner(
        "Paciente Maria Souza Lima retornou.",
        nomes_conhecidos=["Maria", "Maria Souza Lima"],
        nlp=nlp_falso(),
    )

    assert "Souza" not in resultado.texto
    assert "Lima" not in resultado.texto


def test_nome_do_cadastro_nao_casa_dentro_de_outra_palavra():
    """"Ana" nao pode mascarar "anamnese"."""
    resultado = anonimizar_ner(
        "Anamnese sem alteracoes.",
        nomes_conhecidos=["Ana"],
        nlp=nlp_falso(),
    )

    assert resultado.texto == "Anamnese sem alteracoes."
    assert len(resultado.mapa) == 0


# ---------------------------------------------------------------------------
# Entidades do NER
# ---------------------------------------------------------------------------

def test_entidade_per_vira_token_de_pessoa():
    resultado = anonimizar_ner(
        "Encaminhado pelo Dr. Carlos Mendes.",
        nlp=nlp_falso(("Carlos Mendes", "PER")),
    )

    assert "Carlos Mendes" not in resultado.texto
    assert f"[{TIPO_PESSOA}_1]" in resultado.texto


def test_entidade_loc_vira_token_de_local():
    resultado = anonimizar_ner(
        "Reside em Boa Viagem.",
        nlp=nlp_falso(("Boa Viagem", "LOC")),
    )

    assert "Boa Viagem" not in resultado.texto
    assert f"[{TIPO_LOCAL}_1]" in resultado.texto


def test_rotulo_irrelevante_e_ignorado():
    """ORG, MISC e afins nao sao PII de paciente e devem passar."""
    resultado = anonimizar_ner(
        "Exame feito no Laboratorio Central.",
        nlp=nlp_falso(("Laboratorio Central", "ORG")),
    )

    assert resultado.texto == "Exame feito no Laboratorio Central."


def test_sem_modelo_o_texto_passa_intacto():
    """Sem spaCy instalado o sistema degrada, nao quebra."""
    resultado = anonimizar_ner(
        "Maria Souza esteve aqui.",
        carregador=lambda: None,
    )

    assert resultado.texto == "Maria Souza esteve aqui."


# ---------------------------------------------------------------------------
# Excecoes medicas (risco explicito da ADR-03)
# ---------------------------------------------------------------------------

TERMOS_CLINICOS = [
    "Alzheimer", "Parkinson", "Chagas", "Crohn", "Hodgkin", "Down",
    "Cushing", "Hashimoto", "Raynaud", "Glasgow", "Apgar", "Doppler",
]


@pytest.mark.parametrize("termo", TERMOS_CLINICOS)
def test_doenca_eponima_nao_e_mascarada(termo):
    """Mascarar "Parkinson" deixaria a resposta clinica sem sentido."""
    texto = f"Paciente com diagnostico de {termo} em acompanhamento."
    resultado = anonimizar_ner(texto, nlp=nlp_falso((termo, "PER")))

    assert resultado.texto == texto, f"{termo} foi mascarado indevidamente"
    assert len(resultado.mapa) == 0


@pytest.mark.parametrize(
    "expressao", ["doenca de Crohn", "mal de Chagas", "sindrome de Down"]
)
def test_expressao_composta_com_eponimo_e_poupada(expressao):
    resultado = anonimizar_ner(
        f"Historico de {expressao}.", nlp=nlp_falso((expressao, "PER"))
    )

    assert expressao in resultado.texto


def test_excecao_reconhece_termo_com_acento_e_caixa():
    assert e_excecao_medica("Sjögren")
    assert e_excecao_medica("PARKINSON")
    assert e_excecao_medica("doença de Crohn")
    assert not e_excecao_medica("Maria Souza")


def test_nome_real_continua_sendo_mascarado_perto_de_eponimo():
    """A lista de excecoes nao pode virar porta dos fundos."""
    resultado = anonimizar_ner(
        "Maria Souza tem Parkinson.",
        nomes_conhecidos=["Maria Souza"],
        nlp=nlp_falso(("Parkinson", "PER")),
    )

    assert "Maria Souza" not in resultado.texto
    assert "Parkinson" in resultado.texto


# ---------------------------------------------------------------------------
# Integracao das duas camadas
# ---------------------------------------------------------------------------

def test_as_duas_camadas_juntas_removem_tudo():
    texto = (
        "Maria Souza, CPF 529.982.247-25, nascida em 12/03/1980, "
        "mora em Boa Viagem. Queixa de cefaleia ha 3 dias."
    )
    resultado = anonimizar(
        texto,
        nomes_conhecidos=["Maria Souza"],
        nlp=nlp_falso(("Boa Viagem", "LOC")),
    )

    for sensivel in ["Maria Souza", "529.982.247-25", "12/03/1980", "Boa Viagem"]:
        assert sensivel not in resultado.texto, f"{sensivel!r} vazou"

    assert "cefaleia ha 3 dias" in resultado.texto


def test_ida_e_volta_das_duas_camadas(  ):
    """Criterio de aceite do B26: ida e volta exata."""
    texto = (
        "Maria Souza, CPF 529.982.247-25, telefone (81) 99876-5432, "
        "atendida em Boa Viagem no dia 12/03/1980."
    )
    resultado = anonimizar(
        texto,
        nomes_conhecidos=["Maria Souza"],
        nlp=nlp_falso(("Boa Viagem", "LOC")),
    )

    assert resultado.mapa.reidratar(resultado.texto) == texto


def test_tokens_estaveis_entre_mensagens_com_as_duas_camadas():
    mapa = MapaAnonimizacao()
    nlp = nlp_falso(("Boa Viagem", "LOC"))

    primeira = anonimizar(
        "Maria Souza mora em Boa Viagem.", mapa,
        nomes_conhecidos=["Maria Souza"], nlp=nlp,
    )
    segunda = anonimizar(
        "Confirmar endereco de Maria Souza em Boa Viagem.", primeira.mapa,
        nomes_conhecidos=["Maria Souza"], nlp=nlp,
    )

    assert f"[{TIPO_PESSOA}_1]" in segunda.texto
    assert f"[{TIPO_LOCAL}_1]" in segunda.texto
    assert len(segunda.mapa) == 2


def test_regex_roda_antes_do_ner():
    """Se o NER rodasse primeiro, poderia fatiar um CPF ao meio."""
    resultado = anonimizar(
        "CPF 529.982.247-25 do paciente.",
        nlp=nlp_falso(("529.982.247-25", "PER")),
    )

    assert "[CPF_1]" in resultado.texto
    assert f"[{TIPO_PESSOA}_" not in resultado.texto
