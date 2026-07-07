"""
utils.py — Helpers puros compartilhados entre servidor.py e os blueprints.

Mantém funções sem dependência de app/db/socketio para poderem ser importadas
por qualquer módulo sem risco de import circular.
"""
import re
import unicodedata


def norm(s):
    """Normaliza texto para busca: minúsculas, sem acentos, sem espaços nas pontas."""
    if s is None:
        return ""
    s = str(s).strip().lower()
    return unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")


_SKU_RE = re.compile(r"^\s*0*(\d+)\.(\d+)\s*$")


def norm_sku(sku):
    """Normaliza SKU de Venda 'NN.NNNNNN' ignorando zeros à esquerda ('01.000404'
    e '1.000404' viram a mesma chave). SKU não-padrão retorna None (não casa).

    Fonte única compartilhada por servidor.py (consumíveis) e
    equipamentos_importer.py — antes eram três cópias idênticas do mesmo regex,
    o que faria o casamento por SKU divergir se a regra mudasse."""
    m = _SKU_RE.match(sku or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None
