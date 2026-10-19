"""
utils.py — Helpers puros compartilhados entre servidor.py e os blueprints.

Mantém funções sem dependência de app/db/socketio para poderem ser importadas
por qualquer módulo sem risco de import circular.
"""
import os
import re
import unicodedata

from flask import request


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


def ip_do_cliente():
    """IP de quem fez a requisição. Fonte única para audit log e rate limit.

    Por que uma função e não `request.remote_addr` em cada ponto: os limites de
    tentativa do sistema são POR IP (ratelimit.py), e o valor errado aqui não
    causa um log impreciso — causa um bloqueio coletivo. Com o DocTrack atrás do
    túnel do Cloudflare, o `cloudflared` roda no MESMO servidor que o app, então
    toda requisição chega de 127.0.0.1 e, com TRUST_PROXY ligado, do punhado de
    IPs do edge da Cloudflare. Os dois casos colapsam a equipe inteira em uma
    chave só:

      * `DOCTRACK_LIMITE_IP` (30 falhas / 5 min) passaria a valer para o time
        todo somado, e não por pessoa;
      * `DOCTRACK_LIMITE_KILLSWITCH` (3 falhas / 15 min) é o caso grave: três
        tentativas erradas de QUALQUER um trancariam a rota de desbloqueio para
        todo mundo. Num incidente de verdade, quem atacou queima as três de
        propósito e o administrador legítimo fica sem como destravar.

    A ordem de confiança:

      1. sem TRUST_PROXY, só `remote_addr`. Cabeçalho é forjável por quem chama,
         e não há proxy declarado para tê-lo escrito;
      2. com TRUST_PROXY, `CF-Connecting-IP` primeiro. É o cabeçalho que o edge
         da Cloudflare escreve com o IP real de quem acessou, e é o único que
         sobrevive ao túnel;
      3. senão, `remote_addr` — que o ProxyFix já reescreveu a partir do
         X-Forwarded-For (ver servidor.py), mantendo o comportamento anterior
         para quem roda atrás de IIS/nginx sem Cloudflare.
    """
    if os.environ.get("TRUST_PROXY", "").lower() in ("true", "1", "t"):
        cf = (request.headers.get("CF-Connecting-IP") or "").strip()
        if cf:
            return cf
    return request.remote_addr or ""
