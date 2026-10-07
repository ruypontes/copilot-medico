"""Anonimizacao da estrutura crua vinda da extensao (B69 / US016-CA001).

Cobre a lacuna que o B25/B26 deixou: aqueles anonimizavam o texto formatado
que vai ao LLM, mas a ESTRUTURA capturada tambem e persistida em
`dado_extensao.conteudo` - e ia para o banco com nome e CPF em claro.

Os tres cenarios (texto, lista, dicionario) sao os mesmos da versao original
do B69. O que mudou foi o alvo: antes o teste importava
`backend.text_filter.anonymize_extracted_content`, que carrega o modelo
spaCy no import e por isso nao coletava no CI (ver B13/B15). Agora aponta
para `anonimizar_estrutura`, que e o codigo realmente usado pelo server e
roda sem o modelo - a deteccao de nomes e injetada, como nos demais testes
de NER.
"""
from __future__ import annotations

import pytest

from backend.anonimizacao import (
    MapaAnonimizacao,
    TIPO_PESSOA,
    anonimizar,
    anonimizar_estrutura,
)


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------

class _Entidade:
    def __init__(self, texto, rotulo, inicio, fim):
        self.text, self.label_ = texto, rotulo
        self.start_char, self.end_char = inicio, fim


def nlp_falso(*termos):
    """Modelo que marca os termos informados sempre que aparecerem."""

    def _nlp(texto):
        achados = []
        for termo, rotulo in termos:
            inicio = 0
            while (posicao := texto.find(termo, inicio)) >= 0:
                achados.append(_Entidade(termo, rotulo, posicao, posicao + len(termo)))
                inicio = posicao + len(termo)
        return type("Doc", (), {"ents": achados})()

    return _nlp


def anonimizador(mapa=None, nomes=(), nlp=None):
    """Monta o callable que `anonimizar_estrutura` espera, com mapa partilhado."""
    mapa = mapa if mapa is not None else MapaAnonimizacao()

    def _campo(texto):
        resultado = anonimizar(texto, mapa, nomes_conhecidos=nomes, nlp=nlp)
        return resultado.texto, resultado.mapa

    return _campo


# ---------------------------------------------------------------------------
# Os tres formatos aceitos por _normalize_extension_content
# ---------------------------------------------------------------------------

def test_anonimizar_texto_simples():
    """Formato string."""
    conteudo, _ = anonimizar_estrutura(
        "O paciente Joao Silva relatou dor.",
        anonimizador(nomes=["Joao Silva"]),
    )

    assert "Joao Silva" not in conteudo
    assert f"[{TIPO_PESSOA}_1]" in conteudo


def test_anonimizar_lista():
    """Formato lista de {role, text}, o mais comum vindo da extensao."""
    conteudo, _ = anonimizar_estrutura(
        [{"role": "anamnese", "text": "A Maria reclamou de febre."}],
        anonimizador(nomes=["Maria"]),
    )

    assert "Maria" not in conteudo[0]["text"]
    # O rotulo do campo nao e PII e precisa sobreviver, senao o registro
    # perde o significado.
    assert conteudo[0]["role"] == "anamnese"


def test_anonimizar_dicionario():
    """Formato dicionario campo -> valor."""
    conteudo, _ = anonimizar_estrutura(
        {"relato": "O Dr. Ruy Pontes atendeu o paciente."},
        anonimizador(nlp=nlp_falso(("Ruy Pontes", "PER"))),
    )

    assert "Ruy Pontes" not in conteudo["relato"]
    assert "relato" in conteudo


# ---------------------------------------------------------------------------
# O que o anonimizador novo acrescenta ao B69 original
# ---------------------------------------------------------------------------

def test_identificadores_tambem_saem_nao_so_nomes():
    """O B69 original so removia nomes (remover_nomes). CPF e telefone
    tambem sao PII e agora caem na mesma passagem."""
    conteudo, _ = anonimizar_estrutura(
        [
            {"role": "cpf", "text": "529.982.247-25"},
            {"role": "telefone", "text": "(81) 99876-5432"},
            {"role": "nascimento", "text": "12/03/1980"},
        ],
        anonimizador(),
    )

    textos = " ".join(item["text"] for item in conteudo)
    for sensivel in ["529.982.247-25", "(81) 99876-5432", "12/03/1980"]:
        assert sensivel not in textos
    assert "[CPF_1]" in textos and "[TELEFONE_1]" in textos and "[DATA_1]" in textos


def test_mesmo_valor_em_campos_diferentes_recebe_o_mesmo_token():
    """Mapa unico para a estrutura inteira: dois campos com o mesmo CPF nao
    podem virar [CPF_1] e [CPF_2]."""
    conteudo, mapa = anonimizar_estrutura(
        [
            {"role": "cpf", "text": "529.982.247-25"},
            {"role": "observacao", "text": "Confirmar CPF 529.982.247-25."},
        ],
        anonimizador(),
    )

    assert conteudo[0]["text"] == "[CPF_1]"
    assert "[CPF_1]" in conteudo[1]["text"]
    assert len(mapa) == 1


def test_anonimizacao_e_reversivel():
    """Diferenca central para o B69 original: aquele apagava o trecho
    (`texto.replace(nome, "")`) e a informacao se perdia. Agora o medico
    recupera o valor real na exibicao."""
    original = [{"role": "cpf", "text": "529.982.247-25"}]

    conteudo, mapa = anonimizar_estrutura(original, anonimizador())

    assert mapa.reidratar(conteudo[0]["text"]) == "529.982.247-25"


def test_conteudo_clinico_sobrevive():
    conteudo, _ = anonimizar_estrutura(
        [{"role": "queixa", "text": "Cefaleia ha 3 dias, piora ao deitar."}],
        anonimizador(),
    )

    assert conteudo[0]["text"] == "Cefaleia ha 3 dias, piora ao deitar."


# ---------------------------------------------------------------------------
# Robustez da travessia
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "entrada", [None, 42, True, [], {}, "", "   "],
)
def test_valores_nao_textuais_passam_intactos(entrada):
    """Numero, booleano, None e vazio nao sao texto - nao devem quebrar nem
    virar string."""
    conteudo, _ = anonimizar_estrutura(entrada, anonimizador())

    assert conteudo == entrada


def test_estrutura_aninhada_e_percorrida():
    """Lista dentro de dicionario, como o campo `queixa: [...]` que a
    extensao envia."""
    conteudo, _ = anonimizar_estrutura(
        {"sintomas": ["febre", "CPF 529.982.247-25"], "peso": 70},
        anonimizador(),
    )

    assert conteudo["sintomas"][0] == "febre"
    assert "529.982.247-25" not in conteudo["sintomas"][1]
    assert conteudo["peso"] == 70


def test_chaves_do_dicionario_nao_sao_anonimizadas():
    """As chaves sao rotulos de campo; anonimiza-las destruiria o registro."""
    conteudo, _ = anonimizar_estrutura(
        {"nome_do_paciente": "Maria Souza"},
        anonimizador(nomes=["Maria Souza"]),
    )

    assert "nome_do_paciente" in conteudo
    assert conteudo["nome_do_paciente"] != "Maria Souza"
