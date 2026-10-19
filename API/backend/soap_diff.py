"""Versoes IA x medico do SOAP e a diferenca entre elas (B44 / US018).

O `documento_soap` guarda a versao gerada pela IA (`versao_ia`, imutavel) e a
editada pelo medico (`versao_medico`). Aqui ficam a validacao do que o medico
envia e o diff por secao que a extensao exibe:

- secoes de texto (subjetivo, objetivo, avaliacao, plano): diff por palavra;
- secoes em lista (hipoteses, alertas, pendencias): diff por item.

As secoes seguem a descricao do B39 (SoapV1). Quando o schema pydantic do B39
entrar, `validar_versao` passa a delegar para ele; o formato do diff nao muda.
"""
import difflib
import re

SECOES_TEXTO = {
    "subjetivo": "Subjetivo",
    "objetivo": "Objetivo",
    "avaliacao": "Avaliação",
    "plano": "Plano",
}
SECOES_LISTA = {
    "hipoteses": "Hipóteses",
    "alertas": "Alertas",
    "pendencias": "Pendências",
}
SECOES = {**SECOES_TEXTO, **SECOES_LISTA}

MAX_TEXTO = 20_000
MAX_ITENS = 50
MAX_ITEM = 500

# Palavras e espacos como tokens separados: o texto e remontado sem perda.
_TOKENS = re.compile(r"\s+|\S+")


class SoapInvalido(ValueError):
    """Versao do SOAP fora do formato; vira 400 na rota."""


def validar_versao(dados) -> dict:
    """Normaliza uma versao do SOAP: so secoes conhecidas, texto aparado e
    listas sem itens vazios. Secao ausente vale como vazia."""
    if not isinstance(dados, dict):
        raise SoapInvalido("A versao do SOAP deve ser um objeto JSON.")
    desconhecidas = sorted(set(dados) - set(SECOES))
    if desconhecidas:
        raise SoapInvalido(f"Secoes desconhecidas: {', '.join(desconhecidas)}.")

    versao = {}
    for chave in SECOES_TEXTO:
        valor = dados.get(chave) or ""
        if not isinstance(valor, str):
            raise SoapInvalido(f"'{chave}' deve ser texto.")
        if len(valor) > MAX_TEXTO:
            raise SoapInvalido(f"'{chave}' passa de {MAX_TEXTO} caracteres.")
        versao[chave] = valor.strip()
    for chave in SECOES_LISTA:
        valor = dados.get(chave) or []
        if not isinstance(valor, list) or not all(isinstance(item, str) for item in valor):
            raise SoapInvalido(f"'{chave}' deve ser uma lista de textos.")
        itens = [item.strip() for item in valor if item.strip()]
        if len(itens) > MAX_ITENS or any(len(item) > MAX_ITEM for item in itens):
            raise SoapInvalido(f"'{chave}' aceita ate {MAX_ITENS} itens de {MAX_ITEM} caracteres.")
        versao[chave] = itens
    return versao


def _trechos(antes: list[str], depois: list[str], separador: str = "") -> list[dict]:
    """Opcodes do difflib -> [{"op": igual|removido|adicionado, "texto"}].

    Em `separador` vazio os tokens sao concatenados (texto); senao, cada item
    vira um trecho proprio (listas).
    """
    trechos = []

    def _add(op, tokens):
        if not tokens:
            return
        if separador:
            trechos.extend({"op": op, "texto": t} for t in tokens)
        elif trechos and trechos[-1]["op"] == op:
            trechos[-1]["texto"] += "".join(tokens)
        else:
            trechos.append({"op": op, "texto": "".join(tokens)})

    matcher = difflib.SequenceMatcher(a=antes, b=depois, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            _add("igual", antes[i1:i2])
        else:
            # "replace" mostra o que saiu antes do que entrou, como um revisor
            _add("removido", antes[i1:i2])
            _add("adicionado", depois[j1:j2])
    return trechos


def calcular_diff(versao_ia: dict, versao_medico: dict | None) -> dict | None:
    """Diff por secao; None enquanto o medico nao editou."""
    if versao_medico is None:
        return None
    secoes = []
    for chave, titulo in SECOES.items():
        if chave in SECOES_TEXTO:
            antes = _TOKENS.findall(versao_ia.get(chave) or "")
            depois = _TOKENS.findall(versao_medico.get(chave) or "")
            trechos = _trechos(antes, depois)
            tipo = "texto"
        else:
            trechos = _trechos(versao_ia.get(chave) or [], versao_medico.get(chave) or [], "\n")
            tipo = "lista"
        secoes.append({
            "secao": chave,
            "titulo": titulo,
            "tipo": tipo,
            "alterada": any(t["op"] != "igual" for t in trechos),
            "trechos": trechos,
        })
    alteradas = [s["secao"] for s in secoes if s["alterada"]]
    return {"alterado": bool(alteradas), "secoes_alteradas": alteradas, "secoes": secoes}
