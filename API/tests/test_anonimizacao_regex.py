"""Camada regex da anonimizacao (B25 / US016-CA001, CA003).

O criterio de aceite pede 30 exemplos por padrao. Os CPF e CNS sao gerados
com digito verificador correto em vez de digitados a mao: 30 numeros
invalidos escritos no teste passariam despercebidos e dariam uma falsa
sensacao de cobertura.

Alem dos positivos, cada padrao tem negativos - texto clinico que NAO pode
ser mascarado. Mascarar demais corrompe o raciocinio do modelo tanto quanto
mascarar de menos viola a LGPD.
"""
from __future__ import annotations

import pytest

from backend.anonimizacao import anonimizar_regex
from backend.anonimizacao.padroes import (
    TIPO_CEP,
    TIPO_CNS,
    TIPO_CPF,
    TIPO_DATA,
    TIPO_EMAIL,
    TIPO_RG,
    TIPO_TELEFONE,
    valida_cns,
    valida_cpf,
)

QUANTIDADE_EXEMPLOS = 30


# ---------------------------------------------------------------------------
# Geradores de exemplos validos
# ---------------------------------------------------------------------------

def _cpf_com_digitos(base: str) -> str:
    """Completa os 9 primeiros digitos com os dois verificadores."""
    numero = base
    for posicao in (9, 10):
        soma = sum(int(numero[i]) * (posicao + 1 - i) for i in range(posicao))
        numero += str((soma * 10) % 11 % 10)
    return numero


def cpfs_validos(quantidade: int) -> list[str]:
    exemplos: list[str] = []
    semente = 100000000
    while len(exemplos) < quantidade:
        base = str(semente).zfill(9)
        cpf = _cpf_com_digitos(base)
        if valida_cpf(cpf):
            # Alterna entre as duas grafias usuais.
            if len(exemplos) % 2 == 0:
                exemplos.append(f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}")
            else:
                exemplos.append(cpf)
        semente += 7654321
    return exemplos


def cns_validos(quantidade: int) -> list[str]:
    """Metade da familia definitiva (1/2), metade da provisoria (7/8/9)."""
    exemplos: list[str] = []

    semente = 10000000000
    while len(exemplos) < quantidade // 2:
        pis = str(semente).zfill(11)
        soma = sum(int(pis[i]) * (15 - i) for i in range(11))
        verificador = 11 - (soma % 11)
        if verificador == 11:
            verificador = 0
        if verificador == 10:
            soma += 2
            verificador = 11 - (soma % 11)
            candidato = f"{pis}001{verificador}"
        else:
            candidato = f"{pis}000{verificador}"
        if valida_cns(candidato):
            exemplos.append(candidato)
        semente += 987654321

    prefixo = 89800447719000
    while len(exemplos) < quantidade:
        for ultimo in range(10):
            candidato = f"{prefixo}{ultimo}"
            if valida_cns(candidato) and candidato not in exemplos:
                exemplos.append(candidato)
                break
        prefixo += 1
    return exemplos[:quantidade]


def telefones_validos(quantidade: int) -> list[str]:
    ddds = [11, 21, 31, 41, 51, 61, 71, 81, 85, 91]
    exemplos: list[str] = []
    for i in range(quantidade):
        ddd = ddds[i % len(ddds)]
        sufixo = f"{1000 + i * 37:04d}"
        formatos = [
            f"({ddd}) 9{8000 + i:04d}-{sufixo}",   # celular com parenteses
            f"{ddd}9{8000 + i:04d}{sufixo}",        # celular so digitos
            f"({ddd}) 3{200 + i % 800:03d}-{sufixo}",  # fixo
            f"+55 {ddd} 9{8000 + i:04d}-{sufixo}",  # com codigo do pais
        ]
        exemplos.append(formatos[i % len(formatos)])
    return exemplos


def emails_validos(quantidade: int) -> list[str]:
    dominios = ["clinica.com.br", "hospital.org", "gmail.com", "uol.com.br", "exemplo.med.br"]
    return [
        f"paciente{i}.teste@{dominios[i % len(dominios)]}"
        for i in range(quantidade)
    ]


def ceps_validos(quantidade: int) -> list[str]:
    return [f"{50000 + i * 131:05d}-{(i * 7) % 1000:03d}" for i in range(quantidade)]


def rgs_validos(quantidade: int) -> list[str]:
    exemplos: list[str] = []
    for i in range(quantidade):
        digito = "X" if i % 7 == 0 else str(i % 10)
        exemplos.append(f"{10 + i % 90}.{100 + i % 900:03d}.{200 + i % 800:03d}-{digito}")
    return exemplos


def datas_validas(quantidade: int) -> list[str]:
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
             "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    exemplos: list[str] = []
    for i in range(quantidade):
        dia = 1 + (i % 28)
        mes = 1 + (i % 12)
        ano = 1940 + (i % 80)
        formatos = [
            f"{dia:02d}/{mes:02d}/{ano}",
            f"{ano}-{mes:02d}-{dia:02d}",
            f"{dia:02d}-{mes:02d}-{ano}",
            f"{dia} de {meses[mes - 1]} de {ano}",
        ]
        exemplos.append(formatos[i % len(formatos)])
    return exemplos


CASOS = {
    TIPO_CPF: cpfs_validos(QUANTIDADE_EXEMPLOS),
    TIPO_CNS: cns_validos(QUANTIDADE_EXEMPLOS),
    TIPO_TELEFONE: telefones_validos(QUANTIDADE_EXEMPLOS),
    TIPO_EMAIL: emails_validos(QUANTIDADE_EXEMPLOS),
    TIPO_CEP: ceps_validos(QUANTIDADE_EXEMPLOS),
    TIPO_RG: rgs_validos(QUANTIDADE_EXEMPLOS),
    TIPO_DATA: datas_validas(QUANTIDADE_EXEMPLOS),
}


# ---------------------------------------------------------------------------
# 30 exemplos por padrao
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tipo", sorted(CASOS))
def test_cada_padrao_tem_trinta_exemplos(tipo):
    """Guarda o proprio criterio de aceite: se alguem reduzir a lista, falha."""
    assert len(CASOS[tipo]) == QUANTIDADE_EXEMPLOS


@pytest.mark.parametrize(
    "tipo,valor",
    [(tipo, valor) for tipo, valores in sorted(CASOS.items()) for valor in valores],
)
def test_valor_sensivel_vira_token(tipo, valor):
    """O valor some do texto e e trocado por um token do tipo esperado."""
    texto = f"Dado do paciente: {valor} (registrado hoje)."
    resultado = anonimizar_regex(texto)

    assert valor not in resultado.texto, f"{tipo} vazou no texto de saida"
    assert f"[{tipo}_" in resultado.texto, f"token de {tipo} nao foi emitido"
    assert valor in resultado.mapa.valores.values()


@pytest.mark.parametrize(
    "tipo,valor",
    [(tipo, valor) for tipo, valores in sorted(CASOS.items()) for valor in valores],
)
def test_ida_e_volta_restaura_o_original(tipo, valor):
    """Anonimizar e reidratar devolve exatamente o texto de entrada."""
    texto = f"Dado do paciente: {valor} (registrado hoje)."
    resultado = anonimizar_regex(texto)

    assert resultado.mapa.reidratar(resultado.texto) == texto


# ---------------------------------------------------------------------------
# Negativos: o que NAO pode ser mascarado
# ---------------------------------------------------------------------------

NAO_SENSIVEIS = [
    "Paciente com febre ha 3 dias.",
    "Pressao 120/80 mmHg.",
    "Dipirona 500 mg a cada 6 horas.",
    "Saturacao 98%, FC 72 bpm.",
    "Retorno em 15 dias.",
    "Hemoglobina 13.5 g/dL.",
    "Consulta as 14:30.",
    "Paciente de 45 anos.",
    "Dose de 12345678901 unidades.",   # 11 digitos, mas CPF invalido
    "Protocolo 111.111.111-11 do sistema.",  # CPF de digitos repetidos
    "Codigo CID J45.0 confirmado.",
    "Escala de dor 7/10.",
]


@pytest.mark.parametrize("texto", NAO_SENSIVEIS)
def test_texto_clinico_passa_intacto(texto):
    """Nenhum token e emitido para conteudo clinico legitimo."""
    resultado = anonimizar_regex(texto)

    assert resultado.texto == texto, "texto clinico foi mascarado indevidamente"
    assert len(resultado.mapa) == 0


@pytest.mark.parametrize(
    "cpf_invalido",
    ["123.456.789-01", "000.000.000-00", "999.999.999-99", "111.222.333-44"],
)
def test_cpf_com_digito_verificador_errado_nao_e_mascarado(cpf_invalido):
    resultado = anonimizar_regex(f"Numero {cpf_invalido} no prontuario.")

    assert cpf_invalido in resultado.texto
    assert len(resultado.mapa) == 0


@pytest.mark.parametrize("data_impossivel", ["32/01/1980", "15/13/1990", "00/05/2000"])
def test_data_impossivel_nao_e_mascarada(data_impossivel):
    resultado = anonimizar_regex(f"Anotado {data_impossivel} por engano.")

    assert data_impossivel in resultado.texto


# ---------------------------------------------------------------------------
# Estabilidade e deduplicacao
# ---------------------------------------------------------------------------

def test_mesmo_valor_recebe_o_mesmo_token_no_mesmo_texto():
    cpf = cpfs_validos(1)[0]
    resultado = anonimizar_regex(f"CPF {cpf}; confirmar {cpf} novamente.")

    assert resultado.texto.count("[CPF_1]") == 2
    assert len(resultado.mapa) == 1


def test_formatos_diferentes_do_mesmo_cpf_compartilham_token():
    """`529.982.247-25` e `52998224725` sao a mesma pessoa."""
    resultado = anonimizar_regex("CPF 529.982.247-25 ou 52998224725.")

    assert resultado.texto.count("[CPF_1]") == 2
    assert len(resultado.mapa) == 1


def test_tokens_sao_estaveis_entre_mensagens_da_mesma_consulta():
    """Criterio do B25: estabilidade por consulta, nao por mensagem."""
    cpf = cpfs_validos(1)[0]

    primeira = anonimizar_regex(f"Paciente informou CPF {cpf}.")
    segunda = anonimizar_regex(f"Confirmar o CPF {cpf} no cadastro.", primeira.mapa)

    assert "[CPF_1]" in primeira.texto
    assert "[CPF_1]" in segunda.texto
    assert len(segunda.mapa) == 1


def test_valores_distintos_recebem_indices_crescentes():
    um, dois, tres = cpfs_validos(3)
    resultado = anonimizar_regex(f"{um}, {dois} e {tres}.")

    assert "[CPF_1]" in resultado.texto
    assert "[CPF_2]" in resultado.texto
    assert "[CPF_3]" in resultado.texto


def test_mapa_sobrevive_a_serializacao():
    """O B26 persiste o mapa cifrado; a volta precisa manter os contadores."""
    from backend.anonimizacao import MapaAnonimizacao

    cpf, outro = cpfs_validos(2)
    original = anonimizar_regex(f"CPF {cpf}.")

    restaurado = MapaAnonimizacao.de_dicionario(original.mapa.para_dicionario())
    seguinte = anonimizar_regex(f"Agora {outro}.", restaurado)

    # O contador continuou de onde parou, sem reusar [CPF_1] para outro CPF.
    assert "[CPF_2]" in seguinte.texto
    assert restaurado.valores["[CPF_1]"] == cpf


# ---------------------------------------------------------------------------
# Texto realista com varios padroes juntos
# ---------------------------------------------------------------------------

def test_prontuario_completo_nao_vaza_nenhum_padrao():
    """US016-CA003: nenhum dado sensivel pode sobrar no payload de saida."""
    cpf = cpfs_validos(1)[0]
    cns = cns_validos(2)[0]
    sensiveis = [cpf, cns, "12/03/1980", "(81) 99876-5432",
                 "maria@clinica.com.br", "50670-901", "12.345.678-9"]

    texto = (
        f"Paciente CPF {cpf}, CNS {cns}, nascido em 12/03/1980, "
        f"telefone (81) 99876-5432, e-mail maria@clinica.com.br, "
        f"CEP 50670-901, RG 12.345.678-9. Queixa de cefaleia ha 3 dias."
    )

    resultado = anonimizar_regex(texto)

    for valor in sensiveis:
        assert valor not in resultado.texto, f"{valor!r} vazou"

    # O conteudo clinico sobreviveu.
    assert "cefaleia ha 3 dias" in resultado.texto
    # E a volta e exata.
    assert resultado.mapa.reidratar(resultado.texto) == texto


def test_texto_vazio_nao_quebra():
    resultado = anonimizar_regex("")

    assert resultado.texto == ""
    assert len(resultado.mapa) == 0


def test_token_desconhecido_na_resposta_fica_como_esta():
    """Se o modelo inventar `[CPF_9]`, nao podemos chutar um valor."""
    resultado = anonimizar_regex(f"CPF {cpfs_validos(1)[0]}.")

    assert resultado.mapa.reidratar("Ver [CPF_9] agora.") == "Ver [CPF_9] agora."
