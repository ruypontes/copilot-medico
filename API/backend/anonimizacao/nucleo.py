"""Motor de substituicao e mapa token -> valor real (B25 / US016-CA001, CA002).

O mapa e o que torna a anonimizacao REVERSIVEL: o texto sai daqui sem PII
para ir ao LLM, e a resposta volta por `reidratar()` antes de chegar aos
olhos do medico (ADR-03).

`MapaAnonimizacao` e serializavel para que o B26 o persista cifrado por
consulta - e isso que garante "tokens estaveis por consulta": o mesmo CPF
citado na primeira e na decima mensagem recebe `[CPF_1]` nas duas.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .padroes import PADROES, Padrao

# Formato do token. Os colchetes e o sufixo numerico sobrevivem bem ao
# modelo: o Gemini devolve `[CPF_1]` intacto em vez de tentar "corrigir".
_MODELO_TOKEN = "[{tipo}_{indice}]"
_REGEX_TOKEN = re.compile(r"\[([A-Z_]+)_(\d+)\]")


def _normalizar(tipo: str, valor: str) -> str:
    """Chave de deduplicacao.

    `123.456.789-09` e `12345678909` sao o mesmo CPF e devem receber o mesmo
    token. Para e-mail, a caixa nao importa. Para os demais, comparamos so os
    digitos; o texto exibido na reidratacao e sempre a PRIMEIRA grafia vista.
    """
    if tipo == "EMAIL":
        return valor.strip().lower()
    apenas_digitos = re.sub(r"\D", "", valor)
    return apenas_digitos or valor.strip().lower()


@dataclass
class MapaAnonimizacao:
    """Correspondencia bidirecional token <-> valor real de uma consulta."""

    # token -> valor real (o que a reidratacao usa)
    valores: dict[str, str] = field(default_factory=dict)
    # chave normalizada -> token (garante estabilidade e deduplicacao)
    _indice: dict[str, str] = field(default_factory=dict, repr=False)
    # tipo -> ultimo indice emitido
    _contadores: dict[str, int] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        # Reconstroi indice e contadores quando o mapa vem de `de_dicionario`.
        if self.valores and not self._indice:
            for token, valor in self.valores.items():
                casamento = _REGEX_TOKEN.fullmatch(token)
                if not casamento:
                    continue
                tipo, indice = casamento.group(1), int(casamento.group(2))
                self._indice[_normalizar(tipo, valor)] = token
                self._contadores[tipo] = max(self._contadores.get(tipo, 0), indice)

    def token_para(self, tipo: str, valor: str) -> str:
        """Token estavel para `valor`; cria um novo se for a primeira vez."""
        chave = _normalizar(tipo, valor)
        existente = self._indice.get(chave)
        if existente is not None:
            return existente

        proximo = self._contadores.get(tipo, 0) + 1
        self._contadores[tipo] = proximo
        token = _MODELO_TOKEN.format(tipo=tipo, indice=proximo)
        self.valores[token] = valor
        self._indice[chave] = token
        return token

    def reidratar(self, texto: str) -> str:
        """Devolve os valores reais no lugar dos tokens (US016-CA002)."""
        if not texto or not self.valores:
            return texto

        def troca(casamento: re.Match[str]) -> str:
            # Token desconhecido fica como esta: melhor o medico ver
            # `[CPF_9]` do que o sistema inventar um valor.
            return self.valores.get(casamento.group(0), casamento.group(0))

        return _REGEX_TOKEN.sub(troca, texto)

    # -- serializacao (o B26 cifra este dicionario) -------------------------

    def para_dicionario(self) -> dict[str, str]:
        return dict(self.valores)

    @classmethod
    def de_dicionario(cls, dados: dict[str, str] | None) -> "MapaAnonimizacao":
        return cls(valores=dict(dados or {}))

    def __len__(self) -> int:
        return len(self.valores)


@dataclass
class Resultado:
    """Texto pronto para sair da maquina, mais o mapa para o caminho de volta."""

    texto: str
    mapa: MapaAnonimizacao

    @property
    def houve_substituicao(self) -> bool:
        return self.texto != "" and bool(self.mapa)


def _coletar_ocorrencias(texto: str, padroes: tuple[Padrao, ...]) -> list[tuple[int, int, str, str]]:
    """Casamentos validados, sem sobreposicao, em ordem de posicao.

    Quando dois padroes cobrem o mesmo trecho (um CNS tambem casa parcialmente
    como telefone), vence o declarado primeiro em PADROES. Por isso varremos
    na ordem da tabela e descartamos o que colidir com o que ja foi aceito.
    """
    aceitos: list[tuple[int, int, str, str]] = []

    for padrao in padroes:
        for casamento in padrao.regex.finditer(texto):
            inicio, fim = casamento.span()
            trecho = casamento.group(0)
            if not padrao.valida(trecho):
                continue
            # Descarta se encostar em algo ja aceito por um padrao anterior.
            if any(inicio < f and i < fim for i, f, _, _ in aceitos):
                continue
            aceitos.append((inicio, fim, padrao.tipo, trecho))

    aceitos.sort(key=lambda item: item[0])
    return aceitos


def anonimizar_regex(
    texto: str,
    mapa: MapaAnonimizacao | None = None,
    padroes: tuple[Padrao, ...] = PADROES,
) -> Resultado:
    """Camada 1: substitui os padroes deterministicos por tokens.

    Passar o `mapa` de uma consulta anterior mantem os tokens estaveis entre
    mensagens da mesma consulta.
    """
    mapa = mapa if mapa is not None else MapaAnonimizacao()
    if not texto:
        return Resultado(texto=texto or "", mapa=mapa)

    ocorrencias = _coletar_ocorrencias(texto, padroes)
    if not ocorrencias:
        return Resultado(texto=texto, mapa=mapa)

    # Reconstroi a string de uma vez. Substituir in-place deslocaria os
    # indices dos casamentos seguintes.
    partes: list[str] = []
    cursor = 0
    for inicio, fim, tipo, trecho in ocorrencias:
        partes.append(texto[cursor:inicio])
        partes.append(mapa.token_para(tipo, trecho))
        cursor = fim
    partes.append(texto[cursor:])

    return Resultado(texto="".join(partes), mapa=mapa)


def anonimizar_estrutura(
    conteudo,
    anonimizar_texto,
) -> tuple[object, MapaAnonimizacao | None]:
    """Aplica `anonimizar_texto` a cada string de uma estrutura (B69).

    O conteudo raspado do prontuario chega em tres formatos (os mesmos que
    `_normalize_extension_content` aceita):

        [{"role": ..., "text": ...}, ...]   lista de campos
        {"campo": "valor" | [...]}          dicionario
        "texto corrido"

    Anonimizar so o texto formatado que vai ao LLM nao basta: a estrutura
    crua tambem e PERSISTIDA, e sem este passo o banco guardaria o nome e o
    CPF em claro. Percorrer a estrutura (em vez de serializar e anonimizar o
    JSON inteiro) preserva as chaves - sao rotulos de campo, nao dado do
    paciente - e evita que o anonimizador tropece na pontuacao do JSON.

    `anonimizar_texto` recebe uma string e devolve (texto, mapa); o mapa e
    compartilhado entre as chamadas, entao o mesmo CPF recebe o mesmo token
    em todos os campos.
    """
    ultimo_mapa: MapaAnonimizacao | None = None

    def _texto(valor):
        nonlocal ultimo_mapa
        if not isinstance(valor, str) or not valor.strip():
            return valor
        anonimo, mapa = anonimizar_texto(valor)
        ultimo_mapa = mapa
        return anonimo

    def _valor(valor):
        if isinstance(valor, str):
            return _texto(valor)
        if isinstance(valor, list):
            return [_valor(item) for item in valor]
        if isinstance(valor, dict):
            # Chaves sao rotulos de campo, nao PII.
            # Em estruturas vindas da extensao, "role" tambem e um
            # rotulo estrutural ("anamnese", "cpf", "telefone", etc.).
            # Somente os valores devem passar pelo anonimizador.
            resultado = {}
            for chave, sub in valor.items():
                if chave == "role":
                    resultado[chave] = sub
                else:
                    resultado[chave] = _valor(sub)
            return resultado
        # Numeros, booleanos e None passam intactos.
        return valor

    return _valor(conteudo), ultimo_mapa