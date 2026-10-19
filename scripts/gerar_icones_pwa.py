"""
gerar_icones_pwa.py — Gera os PNGs do manifesto a partir da marca do DocTrack.

Roda UMA vez (ou quando a marca mudar) e comita a saída em static/icons/. O app
em produção não depende disto: o Pillow entra hoje de carona no matplotlib, que
só serve a scripts de relatório, e não está declarado em requirements.txt como
dependência de runtime. Ícone é asset, não código que sobe junto.

    .\\venv\\Scripts\\python scripts\\gerar_icones_pwa.py

A marca é o mesmo desenho do <svg> em templates/base.html — quatro quadrados
arredondados em degradê de ciano. Redesenhado aqui em Pillow, e não rasterizado
do SVG, para não arrastar cairosvg/GTK para dentro do projeto: o servidor de
produção é Windows sem admin (ver docs/DEPLOY_SERVIDOR.md) e essa pilha foi
deliberadamente mantida fora dele.

Três formatos, porque os sistemas pedem coisas diferentes:
  * `icone-<n>.png`     — quadrado, `purpose: any`;
  * `icone-maskable.png`— o MESMO desenho com 20% de margem em volta, para o
    Android poder recortar em círculo/squircle sem comer o logotipo;
  * `apple-touch-icon`  — o iOS ignora o manifesto e lê esta <link>; e ignora
    também a transparência, então este vai com fundo chapado.
"""
import os

from PIL import Image, ImageDraw

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(RAIZ, "static", "icons")

# Tokens de static/style.css (tema escuro) e do <svg> da marca em base.html.
FUNDO = (21, 23, 46)          # --bg-void
QUADRADOS = [                 # (coluna, linha, cor RGB, opacidade)
    (0, 0, (0x67, 0xe8, 0xf9), 1.00),
    (1, 0, (0x06, 0xb6, 0xd4), 0.70),
    (0, 1, (0x08, 0x91, 0xb2), 0.50),
    (1, 1, (0x22, 0xd3, 0xee), 0.40),
]

# Desenhamos sempre grande e reduzimos no fim: o Pillow não tem antialiasing em
# `rounded_rectangle`, e sem isto os cantos dos ícones pequenos saem serrilhados.
SUPER = 8


def _desenhar(lado, margem_rel, fundo):
    """Compõe a marca num quadrado de `lado` px.

    `margem_rel` é a fração do lado reservada como respiro em cada borda (0 para
    o ícone comum, 0.20 para o maskable). `fundo` None deixa o PNG transparente.
    """
    n = lado * SUPER
    img = Image.new("RGBA", (n, n), (fundo + (255,)) if fundo else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Área útil da marca depois de descontar o respiro dos dois lados.
    util = n * (1 - 2 * margem_rel)
    origem = (n - util) / 2
    # Proporções do SVG original (quadrado 8, vão 2, raio 2), mas medidas sobre
    # as 18 unidades que a marca REALMENTE ocupa (3..21 do viewBox de 24), não
    # sobre as 24 — senão o bloco fica ancorado no canto e sobra vão à direita
    # e embaixo, em vez de ficar centrado na área útil.
    passo = util / 18 * 10          # 8 do quadrado + 2 do vão
    tam = util / 18 * 8
    raio = util / 18 * 2

    for col, lin, cor, alfa in QUADRADOS:
        x = origem + col * passo
        y = origem + lin * passo
        # Alfa aplicado na cor (e não via camada extra): sobre fundo opaco o
        # efeito é idêntico ao `opacity` do SVG, e o PNG sai com uma camada só.
        d.rounded_rectangle([x, y, x + tam, y + tam], radius=raio,
                            fill=cor + (int(255 * alfa),))

    return img.resize((lado, lado), Image.LANCZOS)


def main():
    os.makedirs(DESTINO, exist_ok=True)
    gerados = []

    for lado in (192, 512):
        arq = os.path.join(DESTINO, f"icone-{lado}.png")
        _desenhar(lado, 0.10, FUNDO).save(arq)
        gerados.append(arq)

    # Maskable: margem generosa porque o Android recorta até ~10% de cada borda
    # e a marca precisa sobreviver inteira ao pior recorte (círculo).
    arq = os.path.join(DESTINO, "icone-maskable-512.png")
    _desenhar(512, 0.20, FUNDO).save(arq)
    gerados.append(arq)

    # iOS: 180px é o tamanho que o Safari pede há várias versões, e ele aplica o
    # arredondamento por conta — mandamos quadrado e opaco.
    arq = os.path.join(DESTINO, "apple-touch-icon.png")
    _desenhar(180, 0.12, FUNDO).save(arq)
    gerados.append(arq)

    for a in gerados:
        print(f"  {os.path.relpath(a, RAIZ)}  ({os.path.getsize(a):,} bytes)")


if __name__ == "__main__":
    main()
