#!/usr/bin/env python3
"""
Gerador de PDF de impressão de cartas.
Layout: A4, grade 3×3, marcas de corte 100% idênticas ao CardTrader.

Uso:
    python3 generate.py imagem1.jpg imagem2.jpg ... -o saida.pdf
    python3 generate.py --dir pasta_com_imagens/ -o saida.pdf
    python3 generate.py --dir pasta/ --logo logo_cardtrader.png -o saida.pdf

As imagens são inseridas em ordem alfabética (caso --dir) ou na ordem informada.
Cada página comporta 9 cartas (3 colunas × 3 linhas).
"""

import argparse
import sys
from pathlib import Path

import fitz  # PyMuPDF

# Caminho do logo (usado como módulo pelo app.py)
LOGO_PATH = Path(__file__).parent / "logo_cardtrader.png"


# ── Medidas exatas extraídas do deck-1.pdf ──────────────────────────────────
PAGE_W = 595.28   # pt  (A4 largura)
PAGE_H = 841.89   # pt  (A4 altura)

# Bordas da grade em coords PyMuPDF (origem topo-esq, Y cresce ↓)
COLS_X = [29.76, 208.35, 386.93, 565.51]   # 4 bordas verticais → 3 colunas
ROWS_Y = [58.58, 308.03, 557.48, 806.93]   # 4 bordas horizontais → 3 linhas

LOGO_RECT = fitz.Rect(208.35, 14.17, 386.93, 44.41)

# Parâmetros das marcas de corte
CUT_ARM    = 14.17   # pt — meio-comprimento do braço da cruz
CUT_OFFSET =  0.29   # pt — folga do triângulo em relação à borda da carta
TRI_SZ     =  8.50   # pt — cateto do triângulo de corte
LINE_W     =  0.57   # pt — espessura das linhas de corte
GRAY  = (0.863, 0.863, 0.863)
DARK  = (0.090, 0.082, 0.067)

CARDS_PER_PAGE = 9


# ── Helpers ─────────────────────────────────────────────────────────────────

def card_slots() -> list[fitz.Rect]:
    """Retorna os 9 Rects dos slots em ordem row-major (linha a linha)."""
    slots = []
    for ri in range(3):
        for ci in range(3):
            slots.append(fitz.Rect(
                COLS_X[ci], ROWS_Y[ri],
                COLS_X[ci + 1], ROWS_Y[ri + 1],
            ))
    return slots


SLOTS = card_slots()


def draw_cut_marks(page: fitz.Page) -> None:
    """Desenha todas as marcas de corte na página."""

    shape = page.new_shape()

    # ── Linhas cinzas de corte ──────────────────────────────────────────────
    # Para cada interseção entre borda de coluna e borda de linha:
    for ci, col_x in enumerate(COLS_X):
        for ri, row_y in enumerate(ROWS_Y):

            # Braço horizontal da cruz
            shape.draw_line((col_x - CUT_ARM, row_y), (col_x + CUT_ARM, row_y))
            # Braço vertical da cruz
            shape.draw_line((col_x, row_y - CUT_ARM), (col_x, row_y + CUT_ARM))

        # Extensão vertical: do topo da página até o braço da 1ª linha
        shape.draw_line((col_x, 0), (col_x, ROWS_Y[0] - CUT_ARM))
        # Extensão vertical: do braço da última linha até fora da página
        shape.draw_line((col_x, ROWS_Y[-1] + CUT_ARM), (col_x, PAGE_H + 999))

        # Coluna esquerda → extensão horizontal à esquerda em cada linha
        if ci == 0:
            for row_y in ROWS_Y:
                shape.draw_line((0, row_y), (col_x - CUT_ARM, row_y))

        # Coluna direita → extensão horizontal à direita (fora da página)
        if ci == len(COLS_X) - 1:
            for row_y in ROWS_Y:
                shape.draw_line((col_x + CUT_ARM, row_y), (PAGE_W + 999, row_y))

    shape.finish(color=GRAY, width=LINE_W, fill=None)

    # ── Triângulos escuros em cada canto de cada carta ──────────────────────
    ox, oy = CUT_OFFSET, CUT_OFFSET
    sz = TRI_SZ

    for slot in SLOTS:
        x0, y0 = slot.x0, slot.y0
        x1, y1 = slot.x1, slot.y1

        # Canto superior-esquerdo: aponta para ↘
        shape.draw_polyline([
            (x0 + ox,      y0 + oy),
            (x0 + ox + sz, y0 + oy),
            (x0 + ox,      y0 + oy + sz),
            (x0 + ox,      y0 + oy),   # fecha
        ])
        shape.finish(color=DARK, fill=DARK, width=0)

        # Canto superior-direito: aponta para ↙
        shape.draw_polyline([
            (x1 - ox,      y0 + oy),
            (x1 - ox - sz, y0 + oy),
            (x1 - ox,      y0 + oy + sz),
            (x1 - ox,      y0 + oy),
        ])
        shape.finish(color=DARK, fill=DARK, width=0)

        # Canto inferior-esquerdo: aponta para ↗
        shape.draw_polyline([
            (x0 + ox,      y1 - oy),
            (x0 + ox + sz, y1 - oy),
            (x0 + ox,      y1 - oy - sz),
            (x0 + ox,      y1 - oy),
        ])
        shape.finish(color=DARK, fill=DARK, width=0)

        # Canto inferior-direito: aponta para ↖
        shape.draw_polyline([
            (x1 - ox,      y1 - oy),
            (x1 - ox - sz, y1 - oy),
            (x1 - ox,      y1 - oy - sz),
            (x1 - ox,      y1 - oy),
        ])
        shape.finish(color=DARK, fill=DARK, width=0)

    shape.commit()


def build_page(
    doc: fitz.Document,
    images: list[Path | None],
    logo_path: Path | None,
) -> None:
    """
    Cria uma nova página no doc com até 9 imagens de cartas.
    Aceita None em qualquer posição para deixar o slot vazio
    (usado nas páginas de verso das DFCs com colunas espelhadas).
    """
    page = doc.new_page(width=PAGE_W, height=PAGE_H)

    for i, img_path in enumerate(images[:CARDS_PER_PAGE]):
        if img_path is None:
            continue          # slot vazio — mantém a grade mas sem imagem
        page.insert_image(SLOTS[i], filename=str(img_path), keep_proportion=False)

    draw_cut_marks(page)


# ── DFC (frente e verso) ─────────────────────────────────────────────────────

def _mirror_col(slot_idx: int, cols: int = 3) -> int:
    """
    Espelha a coluna de um slot para impressão duplex long-edge (padrão A4).
    Ao virar o papel pelo lado longo, col 0 ↔ col 2, col 1 permanece.
    """
    row = slot_idx // cols
    col = slot_idx % cols
    return row * cols + (cols - 1 - col)


def build_dfc_pdf(
    front_images: list[Path],
    back_images:  list[Path],
    logo_path: Path | None,
) -> fitz.Document:
    """
    Gera um Document com pares de páginas frente/verso para DFCs.

    Cada par:
      • Página ímpar  (frente): slots 0..n-1 em ordem normal.
      • Página par    (verso) : slots espelhados horizontalmente para que,
        ao imprimir duplex (flip long-edge), cada verso se alinhe ao frente.

    Exemplo com 2 DFCs (A e B):
      Frente: [A, B, _, _, _, _, _, _, _]  → col 0, col 1
      Verso:  [_, B', A', _, _, _, _, _, _] → col 2=mirror(0), col 1=mirror(1)
    """
    assert len(front_images) == len(back_images), "front e back devem ter o mesmo tamanho"

    doc = fitz.open()

    for start in range(0, len(front_images), CARDS_PER_PAGE):
        fronts = front_images[start : start + CARDS_PER_PAGE]
        backs  = back_images [start : start + CARDS_PER_PAGE]

        # Página de frentes: ordem normal (None = slot vazio, não ocorre aqui)
        build_page(doc, fronts, logo_path)

        # Página de versos: posições espelhadas
        back_slots: list[Path | None] = [None] * CARDS_PER_PAGE
        for i, back_path in enumerate(backs):
            back_slots[_mirror_col(i)] = back_path
        build_page(doc, back_slots, logo_path)

    return doc


def collect_images(paths: list[str], dir_path: str | None) -> list[Path]:
    exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}
    images: list[Path] = []

    if dir_path:
        d = Path(dir_path)
        if not d.is_dir():
            sys.exit(f"Erro: diretório não encontrado: {dir_path}")
        images = sorted(p for p in d.iterdir() if p.suffix.lower() in exts)

    for p in paths:
        pp = Path(p)
        if not pp.exists():
            sys.exit(f"Erro: arquivo não encontrado: {p}")
        images.append(pp)

    return images


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera PDF de impressão de cartas (layout A4, 3×3).",
    )
    parser.add_argument(
        "images", nargs="*",
        help="Imagens das cartas (JPG/PNG). Ordem = ordem de inserção.",
    )
    parser.add_argument(
        "--dir", metavar="PASTA",
        help="Pasta com imagens (ordem alfabética).",
    )
    parser.add_argument(
        "--logo", metavar="LOGO",
        default=str(Path(__file__).parent / "logo_cardtrader.png"),
        help="Caminho do logo no topo (default: logo_cardtrader.png ao lado deste script).",
    )
    parser.add_argument(
        "-o", "--output", metavar="SAIDA", default="output.pdf",
        help="Nome do PDF gerado (default: output.pdf).",
    )
    args = parser.parse_args()

    images = collect_images(args.images, args.dir)
    if not images:
        sys.exit("Erro: nenhuma imagem fornecida. Use arquivos posicionais ou --dir.")

    logo_path = Path(args.logo)

    doc = fitz.open()

    # Divide em páginas de 9 cartas
    for page_start in range(0, len(images), CARDS_PER_PAGE):
        page_imgs = images[page_start : page_start + CARDS_PER_PAGE]
        build_page(doc, page_imgs, logo_path)

    out = Path(args.output)
    doc.save(str(out), garbage=4, deflate=True)
    print(f"PDF gerado: {out}  ({doc.page_count} página(s), {len(images)} carta(s))")


if __name__ == "__main__":
    main()
