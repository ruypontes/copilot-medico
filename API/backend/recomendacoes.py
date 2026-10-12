"""Recomendacoes durante a consulta sobre uma janela parcial (B38 / US020).

O medico pede "Sugestoes" na aba de gravacao e recebe ate 5 itens curtos -
pergunta, exame, diagnostico diferencial ou alerta - calculados sobre as
transcricoes dos ultimos N minutos da consulta. Nada disso vai para o
prontuario: o resultado so e exibido.

Este modulo nao conhece Flask nem o Gemini: monta o trecho enviado, guarda o
prompt versionado e valida a resposta. A rota fica em server.py.
"""
from __future__ import annotations

import json
import re

PROMPT_ID = "recomendacoes"
PROMPT_VERSAO = "2"

JANELA_PADRAO_MIN = 5
JANELA_MAX_MIN = 120  # a gravacao inteira (US017-CA002)
MAX_ITENS = 5  # US020-CA002
MAX_PALAVRAS = 20  # doc 05, secao 7
TIPOS = ("pergunta", "exame", "diferencial", "alerta")

INSTRUCAO = f"""Você é um assistente de documentação clínica para médicos de atenção primária no Brasil.
Você recebe a transcrição dos últimos minutos de uma consulta em andamento. Nomes e documentos
já foram substituídos por marcadores como [PACIENTE] ou [CPF_1]; mantenha os marcadores como estão.

Sugira ao médico, no MÁXIMO {MAX_ITENS} itens, o que vale considerar AGORA:
- "pergunta": algo importante que ainda não foi perguntado;
- "exame": um exame físico ou complementar pertinente;
- "diferencial": um diagnóstico diferencial a considerar;
- "alerta": um sinal de alarme ou risco que merece atenção.

Regras:
- Cada item em português do Brasil, com no máximo {MAX_PALAVRAS} palavras, direto e acionável.
- Nunca feche um diagnóstico nem prescreva; você apoia, quem decide é o médico.
- Use só o que está na transcrição: não invente exames já feitos, resultados ou valores.
- Não cite referências bibliográficas nem links.
- Se não houver nada relevante, devolva a lista vazia.

Responda APENAS com JSON neste formato, sem texto fora dele:
{{"itens": [{{"tipo": "pergunta", "texto": "..."}}]}}"""


class JanelaInvalida(ValueError):
    pass


def validar_janela(valor) -> int:
    """Minutos da janela; ausente usa o padrao."""
    if valor is None or valor == "":
        return JANELA_PADRAO_MIN
    if isinstance(valor, bool):
        raise JanelaInvalida("janela_min deve ser um numero inteiro de minutos.")
    try:
        minutos = int(str(valor).strip())
    except ValueError:
        raise JanelaInvalida("janela_min deve ser um numero inteiro de minutos.") from None
    if not 1 <= minutos <= JANELA_MAX_MIN:
        raise JanelaInvalida(f"janela_min deve estar entre 1 e {JANELA_MAX_MIN}.")
    return minutos


def montar_trecho(transcricoes: list[dict]) -> str:
    """Texto enviado ao modelo: as transcricoes da janela, da mais antiga para
    a mais recente. Usa os turnos com papel (Medico/Paciente) quando existem."""
    blocos = []
    for transcricao in transcricoes:
        turnos = transcricao.get("dialogue") or []
        linhas = [
            f"{t.get('role') or 'Falante'}: {str(t.get('text') or '').strip()}"
            for t in turnos
            if isinstance(t, dict) and str(t.get("text") or "").strip()
        ]
        texto = "\n".join(linhas) or str(transcricao.get("text") or "").strip()
        if texto:
            blocos.append(texto)
    return "\n\n".join(blocos)


def _limitar_palavras(texto: str) -> str:
    palavras = texto.split()
    if len(palavras) <= MAX_PALAVRAS:
        return " ".join(palavras)
    return " ".join(palavras[:MAX_PALAVRAS]).rstrip(",;:.") + "…"


def _carregar_json(resposta: str):
    texto = (resposta or "").strip()
    # O modelo as vezes embrulha o JSON em ```json ... ```.
    cerca = re.search(r"```(?:json)?\s*(.*?)```", texto, re.S)
    if cerca:
        texto = cerca.group(1).strip()
    try:
        return json.loads(texto)
    except ValueError:
        inicio, fim = texto.find("{"), texto.rfind("}")
        if inicio != -1 and fim > inicio:
            try:
                return json.loads(texto[inicio:fim + 1])
            except ValueError:
                return None
        return None


def interpretar_resposta(resposta: str) -> list[dict]:
    """Converte a resposta do modelo em ate MAX_ITENS itens {tipo, texto},
    cada um com ate MAX_PALAVRAS palavras.

    Sem JSON valido, aproveita linhas em formato de lista ("- ..."): melhor
    mostrar a sugestao do que descartar a chamada inteira.
    """
    dados = _carregar_json(resposta)
    brutos = dados.get("itens") if isinstance(dados, dict) else dados if isinstance(dados, list) else None
    if dados is not None and not isinstance(brutos, list):
        return []  # JSON valido mas fora do formato: nao ha o que aproveitar

    if brutos is None:
        brutos = [
            {"tipo": None, "texto": linha.lstrip("-*•0123456789.) ").strip()}
            for linha in (resposta or "").splitlines()
            if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+\S", linha)
        ]

    itens = []
    for bruto in brutos or []:
        if isinstance(bruto, str):
            bruto = {"tipo": None, "texto": bruto}
        if not isinstance(bruto, dict):
            continue
        texto = _limitar_palavras(str(bruto.get("texto") or "").strip())
        if not texto:
            continue
        tipo = str(bruto.get("tipo") or "").strip().lower()
        # Tipo fora da lista (ou lista sem tipo) nao derruba o item.
        itens.append({"tipo": tipo if tipo in TIPOS else "outro", "texto": texto})
        if len(itens) == MAX_ITENS:
            break
    return itens
