"""Material da consulta enviado ao modelo para gerar o SOAP (B40 / US018-CA001).

Junta as tres fontes da consulta, cada uma numa secao propria:

- transcricoes do audio (com os papeis Medico/Paciente quando existem);
- dados do prontuario capturados pela extensao (dado_extensao);
- mensagens do MEDICO no chat (inclui o texto de PDFs anexados).

As respostas do assistente no chat ficam de fora de proposito: sao texto
gerado por IA, e usa-las como fonte do SOAP levaria para o prontuario coisas
que nao foram ditas na consulta.
"""
from __future__ import annotations

from backend.recomendacoes import montar_trecho


def _formatar_conteudo_extensao(conteudo) -> str:
    """Os formatos que a extensao envia: lista de {role, text}, objeto
    campo -> valor (ou lista) e texto corrido."""
    if isinstance(conteudo, str):
        return conteudo.strip()
    if isinstance(conteudo, list):
        linhas = []
        for item in conteudo:
            if isinstance(item, dict):
                rotulo, texto = item.get("role") or item.get("label"), item.get("text") or item.get("value")
                if texto:
                    linhas.append(f"{rotulo}: {texto}" if rotulo else str(texto))
            elif item:
                linhas.append(str(item))
        return "\n".join(linhas)
    if isinstance(conteudo, dict):
        linhas = []
        for campo, valor in conteudo.items():
            if isinstance(valor, list):
                valor = ", ".join(str(v) for v in valor if v)
            elif isinstance(valor, dict):
                valor = _formatar_conteudo_extensao(valor).replace("\n", "; ")
            if valor not in (None, ""):
                linhas.append(f"{campo}: {valor}")
        return "\n".join(linhas)
    return ""


def _texto_da_mensagem(mensagem: dict) -> str:
    partes = mensagem.get("parts") or []
    return "".join(p.get("text", "") for p in partes if isinstance(p, dict)).strip()


def montar_material(transcricoes: list[dict], dados_extensao: list[dict], mensagens: list[dict]) -> str:
    """Texto unico com as fontes da consulta, em ordem cronologica dentro de
    cada secao. Devolve "" se nao houver nada para gerar o SOAP."""
    secoes = []

    trecho = montar_trecho(transcricoes)
    if trecho:
        secoes.append(f"## Transcrição da consulta\n{trecho}")

    dados = [_formatar_conteudo_extensao(d.get("content")) for d in dados_extensao]
    dados = [d for d in dados if d]
    if dados:
        secoes.append("## Dados do prontuário\n" + "\n\n".join(dados))

    do_medico = [_texto_da_mensagem(m) for m in mensagens if m.get("role") == "user"]
    do_medico = [t for t in do_medico if t]
    if do_medico:
        secoes.append("## Anotações do médico e documentos anexados\n" + "\n\n".join(do_medico))

    return "\n\n".join(secoes)
