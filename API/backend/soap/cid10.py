"""Tabela CID-10 embarcada e busca por codigo ou texto (B42 / US018).

Os CSVs do DATASUS (categorias e subcategorias, ver dados/CID10-FONTE.md) ficam na
imagem e sao lidos uma vez so; a busca roda em memoria, sem rede nem banco,
em poucos milissegundos (criterio do B42: < 100 ms).

Codigo casa pelo inicio ("J1" acha J10, J11...; "A00.0" e "A000" sao iguais).
Texto casa sem acento nem caixa e com as palavras em qualquer ordem
("tifoide febre" acha "Febre tifoide"). Ordem do resultado: codigo exato,
codigo pelo inicio, descricao que comeca pelo texto, palavra que comeca pelo
texto e, por ultimo, o texto no meio de uma palavra.
"""
import csv
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DATA_FILES = (
    ("cid10_categories.csv", "CAT"),
    ("cid10_subcategories.csv", "SUBCAT"),
)


@dataclass(frozen=True)
class CID10Entry:
    code: str
    normalized_code: str
    description: str
    normalized_description: str


def _normalize_text(value: str) -> str:
    """Sem acento e caixa; pontuacao vira espaco ("[dengue]" -> " dengue ")."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(
        char if char.isalnum() else " "
        for char in decomposed
        if not unicodedata.combining(char)
    )


def _normalize_code(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


@lru_cache(maxsize=1)
def _load_catalog() -> tuple[CID10Entry, ...]:
    data_directory = Path(__file__).parent / "dados"
    # Por codigo: categorias sem subdivisao (ex.: A90) aparecem nos dois
    # arquivos; fica a primeira, para o codigo nao sair repetido na busca.
    entries: dict[str, CID10Entry] = {}

    for filename, code_column in _DATA_FILES:
        # Os arquivos do DATASUS vem em Windows-1252, como publicados.
        with (data_directory / filename).open(encoding="cp1252", newline="") as catalog_file:
            for row in csv.DictReader(catalog_file, delimiter=";"):
                raw_code = (row.get(code_column) or "").strip().upper()
                description = (row.get("DESCRICAO") or "").strip()
                if not raw_code or not description:
                    continue

                normalized_code = _normalize_code(raw_code)
                if normalized_code in entries:
                    continue
                code = f"{raw_code[:3]}.{raw_code[3:]}" if len(raw_code) == 4 else raw_code
                entries[normalized_code] = CID10Entry(
                    code=code,
                    normalized_code=normalized_code,
                    description=description,
                    normalized_description=" " + _normalize_text(description),
                )

    return tuple(sorted(entries.values(), key=lambda entry: entry.normalized_code))


def preload() -> None:
    """Le os CSVs na subida do servidor: a primeira busca nao paga a leitura."""
    _load_catalog()


def _rank(entry: CID10Entry, code: str, words: list[str]) -> int | None:
    """Posicao do item no resultado (menor primeiro) ou None se nao casa."""
    if code and entry.normalized_code.startswith(code):
        return 0 if entry.normalized_code == code else 1
    if not words or not all(word in entry.normalized_description for word in words):
        return None
    first = words[0]
    if entry.normalized_description.startswith(" " + first):
        return 2
    return 3 if f" {first}" in entry.normalized_description else 4


def search(query: str, limit: int = 20) -> list[dict[str, str]]:
    code = _normalize_code(query)
    words = _normalize_text(query).split()
    if not code and not words:
        return []

    found = []
    for position, entry in enumerate(_load_catalog()):
        rank = _rank(entry, code, words)
        if rank is not None:
            found.append((rank, position, entry))

    found.sort(key=lambda item: item[:2])
    return [{"code": entry.code, "description": entry.description} for _, _, entry in found[:limit]]
