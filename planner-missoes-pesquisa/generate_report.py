# -*- coding: utf-8 -*-
"""
Consolida os JSONs de results/ num report.md, seguindo fields.yaml.
- Cobre todos os campos por categoria.
- Pula campos marcados como incertos (nome no array `uncertain`) e valores com "[uncertain]".
- Índice com âncora por item + tag curta de veredito (COPY/ADAPT/AVOID) quando presente.
"""
import json
import re
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"
FIELDS_YAML = BASE / "fields.yaml"
OUTLINE_YAML = BASE / "outline.yaml"
OUT = BASE / "report.md"

# Ordem canônica dos itens (segue o outline)
try:
    OUTLINE = yaml.safe_load(OUTLINE_YAML.read_text(encoding="utf-8"))
    ITEM_ORDER = [it["id"] for it in OUTLINE.get("items", [])]
    TOPIC = OUTLINE.get("topic", "").strip()
except Exception:
    ITEM_ORDER = []
    TOPIC = ""

FIELDS = yaml.safe_load(FIELDS_YAML.read_text(encoding="utf-8"))

# Categorias na ordem do fields.yaml (ignora a chave reservada `uncertain`)
CATEGORY_ORDER = [k for k in FIELDS.keys() if k != "uncertain" and isinstance(FIELDS[k], dict)]

CATEGORY_TITLES = {
    "modelo_de_dados": "Modelo de dados",
    "ordenacao": "Ordenação",
    "atributos_cartao": "Atributos do cartão",
    "views": "Views",
    "dependencias_scheduling": "Dependências & scheduling",
    "colaboracao": "Colaboração",
    "replicavel_offline": "Replicável offline (veredito p/ DocTrack)",
}

FIELD_LABELS = {}
for cat in CATEGORY_ORDER:
    for f in FIELDS[cat].get("fields", []):
        FIELD_LABELS[f["name"]] = f["name"].replace("_", " ")


def slug(text):
    s = text.lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s.strip())
    return s


def is_uncertain(name, value, uncertain_list):
    if name in uncertain_list:
        return True
    if value is None:
        return True
    if isinstance(value, str):
        if not value.strip():
            return True
        if "[uncertain]" in value:
            return True
    return False


def short_verdict(text):
    """Extrai um resumo COPY/ADAPT/AVOID curto do campo veredito."""
    if not isinstance(text, str):
        return ""
    tags = []
    for tag in ("COPY", "ADAPT", "AVOID"):
        if re.search(r"\b" + tag + r"\b", text):
            tags.append(tag)
    return " · ".join(tags)


def load_items():
    items = {}
    for p in RESULTS.glob("*.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        data["_file"] = p.name
        items[data.get("id", p.stem)] = data
    # ordena pelo outline; itens não listados vão ao fim
    ordered = [items[i] for i in ITEM_ORDER if i in items]
    ordered += [items[k] for k in items if k not in ITEM_ORDER]
    return ordered


def render_value(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for el in value:
            if isinstance(el, dict):
                parts.append(" | ".join(f"{k}: {v}" for k, v in el.items()))
            else:
                parts.append(str(el))
        return "<br>".join(f"- {p}" for p in parts)
    if isinstance(value, dict):
        return "; ".join(f"**{k}**: {v}" for k, v in value.items())
    return str(value)


def main():
    items = load_items()
    lines = []
    lines.append("# Relatório de Pesquisa — Referências para o módulo *Missões* (kanban nativo)\n")
    if TOPIC:
        lines.append(f"> {TOPIC}\n")
    lines.append(f"*Itens pesquisados: {len(items)} · gerado a partir de `results/*.json` "
                 f"contra `fields.yaml` ({sum(len(FIELDS[c].get('fields', [])) for c in CATEGORY_ORDER)} campos "
                 f"em {len(CATEGORY_ORDER)} categorias).*\n")

    # Índice
    lines.append("## Índice\n")
    for idx, it in enumerate(items, 1):
        name = it.get("research_name") or it.get("name") or it.get("id", "?")
        anchor = f"item-{idx}-{slug(name)}"
        verdict = short_verdict(
            (it.get("replicavel_offline") or {}).get("veredito_copy_adapt_avoid", "")
        )
        tag = f" — **{verdict}**" if verdict else ""
        lines.append(f"{idx}. [{name}](#{anchor}){tag}")
    lines.append("")

    # Detalhe por item
    for idx, it in enumerate(items, 1):
        name = it.get("research_name") or it.get("name") or it.get("id", "?")
        anchor = f"item-{idx}-{slug(name)}"
        uncertain_list = it.get("uncertain", []) or []
        lines.append(f'<a id="{anchor}"></a>')
        lines.append(f"## {idx}. {name}\n")
        for cat in CATEGORY_ORDER:
            block = it.get(cat)
            if not isinstance(block, dict):
                continue
            cat_title = CATEGORY_TITLES.get(cat, cat.replace("_", " ").title())
            # coleta campos não incertos
            rendered = []
            for f in FIELDS[cat].get("fields", []):
                fname = f["name"]
                val = block.get(fname)
                if is_uncertain(fname, val, uncertain_list):
                    continue
                label = FIELD_LABELS.get(fname, fname.replace("_", " "))
                rendered.append((label, render_value(val)))
            if not rendered:
                continue
            lines.append(f"### {cat_title}\n")
            for label, val in rendered:
                lines.append(f"**{label}** — {val}\n")
        # nota de incertos
        if uncertain_list:
            lines.append("> Campos marcados como incertos (não consolidados): "
                         + ", ".join(f"`{u}`" for u in uncertain_list) + "\n")
        lines.append("---\n")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"OK -> {OUT}  ({len(items)} itens)")


if __name__ == "__main__":
    sys.exit(main())
