"""Camada 1 da anonimizacao: padroes deterministicos por regex (B25 / US016-CA001).

Cobre CPF, RG, CNS, telefone, e-mail, CEP e datas completas.

Duas decisoes importantes:

1. **Validacao de digito verificador.** CPF e CNS tem checksum, e nos o
   conferimos antes de mascarar. Sem isso, qualquer sequencia de 11 digitos
   (dosagem, numero de registro, codigo de exame) viraria `[CPF_1]` e o texto
   chegaria mutilado ao modelo. Mascarar demais degrada a resposta clinica
   tanto quanto mascarar de menos viola a LGPD.

2. **Datas completas, nao datas parciais.** `12/03/1980` identifica; `12/03`
   ou `março de 1980` nao. A US016 pede "datas completas", entao exigimos
   dia + mes + ano. Idade e intervalo ("ha 3 dias") passam intactos, que e o
   que o raciocinio clinico precisa.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

# Tipos de token. O valor e o sufixo usado em `[CPF_1]`, `[DATA_2]`, etc.
TIPO_CPF = "CPF"
TIPO_RG = "RG"
TIPO_CNS = "CNS"
TIPO_TELEFONE = "TELEFONE"
TIPO_EMAIL = "EMAIL"
TIPO_CEP = "CEP"
TIPO_DATA = "DATA"


def _so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


# ---------------------------------------------------------------------------
# Validadores de digito verificador
# ---------------------------------------------------------------------------

def valida_cpf(valor: str) -> bool:
    """CPF com os dois digitos verificadores corretos (modulo 11)."""
    digitos = _so_digitos(valor)
    if len(digitos) != 11:
        return False
    # 111.111.111-11 e afins passam no modulo 11 mas nao sao CPF validos.
    if len(set(digitos)) == 1:
        return False
    for posicao in (9, 10):
        soma = sum(int(digitos[i]) * (posicao + 1 - i) for i in range(posicao))
        verificador = (soma * 10) % 11 % 10
        if verificador != int(digitos[posicao]):
            return False
    return True


def valida_cns(valor: str) -> bool:
    """Cartao Nacional de Saude (15 digitos).

    Duas familias: cartoes definitivos comecam em 1 ou 2 e derivam do PIS;
    provisorios comecam em 7, 8 ou 9 e so exigem soma ponderada divisivel
    por 11.
    """
    digitos = _so_digitos(valor)
    if len(digitos) != 15:
        return False

    if digitos[0] in "12":
        pis = digitos[:11]
        soma = sum(int(pis[i]) * (15 - i) for i in range(11))
        verificador = 11 - (soma % 11)
        if verificador == 11:
            verificador = 0
        if verificador == 10:
            # Regra do CNS: soma 2 e recalcula, e o sufixo vira "001".
            soma += 2
            verificador = 11 - (soma % 11)
            esperado = f"{pis}001{verificador}"
        else:
            esperado = f"{pis}000{verificador}"
        return esperado == digitos

    if digitos[0] in "789":
        soma = sum(int(digitos[i]) * (15 - i) for i in range(15))
        return soma % 11 == 0

    return False


def _data_plausivel(dia: int, mes: int, ano: int) -> bool:
    """Rejeita 32/13/1980 e anos fora de uma faixa humana razoavel."""
    if not 1 <= mes <= 12:
        return False
    if not 1900 <= ano <= 2100:
        return False
    dias_por_mes = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return 1 <= dia <= dias_por_mes[mes - 1]


MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}


# ---------------------------------------------------------------------------
# Validadores de contexto por padrao
# ---------------------------------------------------------------------------

def _valida_data_numerica(texto: str) -> bool:
    partes = re.split(r"[/.\-]", texto)
    if len(partes) != 3:
        return False
    if len(partes[0]) == 4:  # ISO: aaaa-mm-dd
        ano, mes, dia = partes
    else:                     # BR: dd/mm/aaaa
        dia, mes, ano = partes
    try:
        return _data_plausivel(int(dia), int(mes), int(ano))
    except ValueError:
        return False


def _valida_data_extenso(texto: str) -> bool:
    match = re.match(
        r"(\d{1,2})\s+de\s+([a-zçã]+)\s+de\s+(\d{4})", texto.lower()
    )
    if not match:
        return False
    mes = MESES.get(match.group(2))
    if mes is None:
        return False
    return _data_plausivel(int(match.group(1)), mes, int(match.group(3)))


def _valida_telefone(texto: str) -> bool:
    """Fixo (10) ou movel (11) digitos, com DDD valido; aceita +55."""
    digitos = _so_digitos(texto)
    if digitos.startswith("55") and len(digitos) in (12, 13):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11):
        return False
    ddd = int(digitos[:2])
    if not 11 <= ddd <= 99:
        return False
    # Celular tem 11 digitos e o nono sempre e 9.
    if len(digitos) == 11 and digitos[2] != "9":
        return False
    # Fixo nao comeca em 0 nem 1 apos o DDD.
    if len(digitos) == 10 and digitos[2] in "01":
        return False
    return True


def _sempre_valido(_texto: str) -> bool:
    return True


# ---------------------------------------------------------------------------
# Tabela de padroes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Padrao:
    tipo: str
    regex: re.Pattern[str]
    # Confirma o casamento (checksum, plausibilidade). Um casamento rejeitado
    # e simplesmente ignorado, deixando o texto original passar.
    valida: Callable[[str], bool] = _sempre_valido


# A ORDEM IMPORTA: o motor resolve sobreposicoes dando prioridade ao padrao
# declarado primeiro. CNS (15 digitos) vem antes de CPF (11) e de telefone,
# senao um CNS seria fatiado por um padrao mais curto.
PADROES: tuple[Padrao, ...] = (
    # E-mail primeiro de todos: pode conter digitos que pareceriam CEP/telefone.
    Padrao(
        TIPO_EMAIL,
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    Padrao(
        TIPO_CNS,
        re.compile(r"\b\d{3}[\s.]?\d{4}[\s.]?\d{4}[\s.]?\d{4}\b"),
        valida_cns,
    ),
    Padrao(
        TIPO_CPF,
        re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
        valida_cpf,
    ),
    # Data por extenso antes da numerica (nao competem, mas mantem a leitura).
    Padrao(
        TIPO_DATA,
        re.compile(
            r"\b\d{1,2}\s+de\s+(?:janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho"
            r"|agosto|setembro|outubro|novembro|dezembro)\s+de\s+\d{4}\b",
            re.IGNORECASE,
        ),
        _valida_data_extenso,
    ),
    Padrao(
        TIPO_DATA,
        re.compile(r"\b(?:\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}|\d{4}-\d{1,2}-\d{1,2})\b"),
        _valida_data_numerica,
    ),
    # Telefone antes de CEP: (81) 3232-1010 contem um bloco 8 digitos.
    Padrao(
        TIPO_TELEFONE,
        re.compile(
            r"(?:\+?55\s?)?(?:\(\d{2}\)|\b\d{2})\s?9?\d{4}[-\s.]?\d{4}\b"
        ),
        _valida_telefone,
    ),
    Padrao(
        TIPO_CEP,
        re.compile(r"\b\d{5}-\d{3}\b"),
    ),
    # RG nao tem checksum nacional: exigimos a pontuacao para nao transformar
    # qualquer numero de 8-9 digitos em RG. Sem os pontos, o risco de falso
    # positivo supera o ganho.
    Padrao(
        TIPO_RG,
        re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}-[0-9Xx]\b"),
    ),
)
