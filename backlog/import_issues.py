#!/usr/bin/env python3
"""Cria issues no GitHub a partir do backlog em CSV.

Uso:
    python import_issues.py                 # dry-run: mostra o que faria
    python import_issues.py --apply         # cria labels, milestones e issues
    python import_issues.py --apply --sprint S0 --sprint S1

Autenticacao (na ordem):
    1. variavel de ambiente GITHUB_TOKEN ou GH_TOKEN
    2. `gh auth token`, se o GitHub CLI estiver instalado

O script e idempotente: issues cujo titulo ja comeca com "[Bxx]" sao puladas.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"

# Cores dos labels (hex sem #)
COR_EPICO = {
    "Base": "5319e7",
    "PEP": "0e8a16",
    "Dados": "1d76db",
    "Identidade": "b60205",
    "Privacidade": "d93f0b",
    "Áudio": "fbca04",
    "Qualidade": "006b75",
    "SOAP": "c2e0c6",
    "Export": "bfd4f2",
    "Piloto": "f9d0c4",
    "Release": "e99695",
}
COR_TIPO = {
    "feat": "a2eeef",
    "fix": "d73a4a",
    "chore": "cfd3d7",
    "docs": "0075ca",
    "test": "bfdadc",
    "refactor": "fef2c0",
}
COR_PONTOS = "ededed"
COR_FLAG = "d4c5f9"


def token() -> str:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok.strip()
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=30
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    sys.exit(
        "Sem credencial: defina GITHUB_TOKEN (escopo 'repo') ou rode `gh auth login`."
    )


class Client:
    def __init__(self, repo: str, tok: str) -> None:
        self.repo = repo
        self.tok = tok

    def request(self, method: str, path: str, body: dict | None = None):
        url = path if path.startswith("http") else f"{API}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.tok}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "backlog-import")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")
            raise RuntimeError(f"{method} {url} -> {err.code}: {detail}") from err

    def paginate(self, path: str) -> list:
        items: list = []
        page = 1
        while True:
            batch = self.request("GET", f"{path}&page={page}&per_page=100")
            if not batch:
                break
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return items


def carregar(caminho: str) -> list[dict]:
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def corpo(row: dict) -> str:
    refs = [r.strip() for r in row["refs"].split(";") if r.strip()]
    linhas = [
        "## Descrição",
        "",
        row["descricao"].strip() or "_(sem descrição)_",
        "",
        "## Critério de aceite",
        "",
        row["criterio_de_aceite"].strip() or "_(a definir)_",
        "",
        "## Metadados",
        "",
        f"| Campo | Valor |",
        f"| --- | --- |",
        f"| ID | `{row['id']}` |",
        f"| Sprint | {row['sprint']} |",
        f"| Épico | {row['epico']} |",
        f"| Tipo | {row['tipo']} |",
        f"| Pontos | {row['pontos']} |",
        f"| Refs | {', '.join(refs) if refs else '—'} |",
    ]
    flags = [f.strip() for f in row["flags"].split(";") if f.strip()]
    if flags:
        linhas += ["", f"> **Flags:** {', '.join(flags)}"]
    linhas += ["", "---", "", "_Importado de `backlog/backlog-v5.csv`._"]
    return "\n".join(linhas)


def labels_de(row: dict) -> list[str]:
    out = [f"epico:{row['epico']}", f"tipo:{row['tipo']}", f"pontos:{row['pontos']}"]
    out += [f.strip() for f in row["flags"].split(";") if f.strip()]
    return out


def sincronizar_labels(cli: Client, rows: list[dict], aplicar: bool) -> None:
    existentes = {
        lb["name"] for lb in cli.paginate(f"/repos/{cli.repo}/labels?")
    }
    desejados: dict[str, tuple[str, str]] = {}
    for row in rows:
        desejados[f"epico:{row['epico']}"] = (
            COR_EPICO.get(row["epico"], "ededed"),
            f"Épico {row['epico']}",
        )
        desejados[f"tipo:{row['tipo']}"] = (
            COR_TIPO.get(row["tipo"], "ededed"),
            f"Tipo {row['tipo']}",
        )
        desejados[f"pontos:{row['pontos']}"] = (
            COR_PONTOS,
            f"Estimativa: {row['pontos']} ponto(s)",
        )
        for flag in (f.strip() for f in row["flags"].split(";")):
            if flag:
                desejados[flag] = (COR_FLAG, "Flag do backlog")

    faltando = sorted(set(desejados) - existentes)
    print(f"Labels: {len(existentes)} no repo, {len(faltando)} a criar")
    for nome in faltando:
        cor, desc = desejados[nome]
        print(f"  + label {nome}")
        if aplicar:
            cli.request(
                "POST",
                f"/repos/{cli.repo}/labels",
                {"name": nome, "color": cor, "description": desc},
            )


def sincronizar_milestones(cli: Client, rows: list[dict], aplicar: bool) -> dict[str, int]:
    atuais = {
        ms["title"]: ms["number"]
        for ms in cli.paginate(f"/repos/{cli.repo}/milestones?state=all")
    }
    sprints = sorted({row["sprint"] for row in rows})
    print(f"Milestones: {len(atuais)} no repo, alvo {sprints}")
    for sprint in sprints:
        if sprint in atuais:
            continue
        print(f"  + milestone {sprint}")
        if aplicar:
            ms = cli.request(
                "POST",
                f"/repos/{cli.repo}/milestones",
                {"title": sprint, "description": f"Sprint {sprint[1:]}"},
            )
            atuais[sprint] = ms["number"]
    return atuais


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(os.path.dirname(__file__), "backlog-v5.csv"))
    ap.add_argument("--repo", default="RiquelmeLopes/copilot-medico")
    ap.add_argument("--apply", action="store_true", help="cria de verdade")
    ap.add_argument("--sprint", action="append", help="filtra por sprint (repetível)")
    args = ap.parse_args()

    rows = carregar(args.csv)
    if args.sprint:
        rows = [r for r in rows if r["sprint"] in set(args.sprint)]
    if not rows:
        return print("Nenhuma linha após o filtro.") or 1

    cli = Client(args.repo, token())
    print(f"Repo: {args.repo} | linhas: {len(rows)} | modo: {'APPLY' if args.apply else 'dry-run'}\n")

    sincronizar_labels(cli, rows, args.apply)
    milestones = sincronizar_milestones(cli, rows, args.apply)

    abertas = cli.paginate(f"/repos/{cli.repo}/issues?state=all")
    ja_existem = {
        t[1:4]
        for t in (i["title"] for i in abertas if "pull_request" not in i)
        if t.startswith("[B") and t[4:5] == "]"
    }
    print(f"\nIssues existentes com prefixo [Bxx]: {len(ja_existem)}\n")

    criadas = puladas = 0
    for row in rows:
        titulo = f"[{row['id']}] {row['titulo']}"
        if row["id"] in ja_existem:
            print(f"  = {titulo}  (já existe, pulando)")
            puladas += 1
            continue
        payload = {
            "title": titulo,
            "body": corpo(row),
            "labels": labels_de(row),
        }
        if row["sprint"] in milestones:
            payload["milestone"] = milestones[row["sprint"]]
        if args.apply:
            issue = cli.request("POST", f"/repos/{cli.repo}/issues", payload)
            print(f"  + #{issue['number']} {titulo}")
            time.sleep(1.2)  # folga para o limite de criação de conteúdo
        else:
            print(f"  + {titulo}  [{', '.join(payload['labels'])}]")
        criadas += 1

    print(f"\n{'Criadas' if args.apply else 'A criar'}: {criadas} | puladas: {puladas}")
    if not args.apply:
        print("\nNada foi enviado. Rode de novo com --apply para criar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
