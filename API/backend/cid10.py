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
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _normalize_code(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


@lru_cache(maxsize=1)
def _load_catalog() -> tuple[CID10Entry, ...]:
    data_directory = Path(__file__).parent
    entries = []

    for filename, code_column in _DATA_FILES:
        with (data_directory / filename).open(
            encoding="cp1252", newline=""
        ) as catalog_file:
            for row in csv.DictReader(catalog_file, delimiter=";"):
                raw_code = (row.get(code_column) or "").strip().upper()
                description = (row.get("DESCRICAO") or "").strip()
                if not raw_code or not description:
                    continue

                code = f"{raw_code[:3]}.{raw_code[3:]}" if len(raw_code) == 4 else raw_code
                entries.append(CID10Entry(
                    code=code,
                    normalized_code=_normalize_code(raw_code),
                    description=description,
                    normalized_description=_normalize_text(description),
                ))

    return tuple(sorted(entries, key=lambda entry: entry.normalized_code))


def preload() -> None:
    _load_catalog()


def search(query: str, limit: int = 20) -> list[dict[str, str]]:
    normalized_text = _normalize_text(query.strip())
    normalized_code = _normalize_code(query)
    results = []

    for entry in _load_catalog():
        if (
            normalized_code in entry.normalized_code
            or normalized_text in entry.normalized_description
        ):
            results.append({"code": entry.code, "description": entry.description})
            if len(results) == limit:
                break

    return results