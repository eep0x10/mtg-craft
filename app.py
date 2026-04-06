#!/usr/bin/env python3
"""
MTG Craft — Backend Flask
Porta: 5001

Endpoints:
  GET  /                       → frontend SPA
  GET  /api/search?q=<query>   → busca no Scryfall
  POST /api/upload             → upload de imagem local
  GET  /api/thumb/<file>       → serve thumbnail de upload
  POST /api/generate           → gera e retorna o PDF
  POST /api/import-deck-url    → importa deck por URL (Moxfield, Archidekt)
  POST /api/proxy-image        → baixa imagem de URL externa (MTGBuilder, etc.)
  GET  /api/card-info?name=    → busca type_line + imagens por nome exato
  GET  /api/cockatrice/decks   → lista arquivos .cod no diretório Cockatrice
  GET  /api/cockatrice/deck/<f>→ lê e parseia um arquivo .cod
  POST /api/cockatrice/save    → salva deck atual como .cod
"""

import hashlib
import io
import re
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import fitz
import requests as req
from flask import Flask, abort, jsonify, request, send_file

from generate import CARDS_PER_PAGE, LOGO_PATH, build_dfc_pdf, build_page

# ── Dirs ──────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
CACHE_DIR  = BASE_DIR / "cache"
UPLOAD_DIR = BASE_DIR / "uploads"
CACHE_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="static")

SCRYFALL = "https://api.scryfall.com"
HEADERS  = {"User-Agent": "CardPDFGen/1.0"}
_last_req = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────

def scryfall(url: str, **params) -> req.Response:
    """GET com rate-limit de 100ms."""
    global _last_req
    wait = 0.1 - (time.time() - _last_req)
    if wait > 0:
        time.sleep(wait)
    r = req.get(url, params=params or None, headers=HEADERS, timeout=15)
    _last_req = time.time()
    return r


def card_data(c: dict) -> dict:
    """
    Extrai os campos relevantes de um objeto Scryfall.
    Detecta DFCs (transform / modal_dfc) e expõe back_png + back_thumb.
    """
    faces = c.get("card_faces") or []
    top_iuri = c.get("image_uris")

    # É DFC imprimível quando NÃO há image_uris no nível raiz E
    # ambas as faces têm image_uris próprias (transform, modal_dfc).
    is_dfc = (
        not top_iuri
        and len(faces) >= 2
        and bool(faces[0].get("image_uris"))
        and bool(faces[1].get("image_uris"))
    )

    if is_dfc:
        iuri_front = faces[0]["image_uris"]
        iuri_back  = faces[1]["image_uris"]
    else:
        iuri_front = top_iuri or (faces[0].get("image_uris") if faces else {}) or {}
        iuri_back  = {}

    # type_line: prefer top-level; DFCs use front face
    type_line = (
        c.get("type_line")
        or (faces[0].get("type_line") if faces else "")
        or ""
    )

    return {
        "id":               c["id"],
        "name":             c["name"],
        "set_name":         c.get("set_name", ""),
        "set_code":         c.get("set", ""),
        "collector_number": c.get("collector_number", ""),
        "lang":             c.get("lang", "en"),
        "is_dfc":           is_dfc,
        "type_line":        type_line,
        "thumb":            iuri_front.get("small", ""),
        "normal":           iuri_front.get("normal", ""),
        "png":              iuri_front.get("png", ""),
        "back_thumb":       iuri_back.get("small", ""),
        "back_png":         iuri_back.get("png", ""),
    }


def download_png(url: str) -> Path:
    """Baixa e cacheia uma imagem pelo URL."""
    key  = hashlib.md5(url.encode()).hexdigest()
    path = CACHE_DIR / f"{key}.png"
    if not path.exists():
        r = scryfall(url)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


# ── Rotas ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/search")
def search():
    q    = request.args.get("q", "").strip()
    lang = request.args.get("lang", "en").strip() or "en"
    if not q:
        return jsonify([])

    if lang != "en":
        # Tenta no idioma solicitado primeiro
        query = f"({q}) lang:{lang}"
        r = scryfall(f"{SCRYFALL}/cards/search", q=query, order="name", unique="cards")
        if r.ok:
            results = r.json().get("data", [])[:20]
            if results:
                return jsonify([card_data(c) for c in results])
        # Fallback para inglês se não encontrou resultados
        lang = "en"

    # Inglês (padrão ou fallback)
    query = f"({q}) lang:en"
    r = scryfall(f"{SCRYFALL}/cards/search", q=query, order="name", unique="cards")
    if r.status_code == 404:
        return jsonify([])
    if not r.ok:
        return jsonify({"error": r.json().get("details", "Erro Scryfall")}), 502
    results = r.json().get("data", [])[:20]
    # Filtra qualquer resultado que não seja inglês (segurança extra)
    results = [c for c in results if c.get("lang", "en") == "en"]
    return jsonify([card_data(c) for c in results])


@app.route("/api/card-by-set/<set_code>/<path:number>")
def card_by_set(set_code: str, number: str):
    """
    Busca carta pelo set code + collector number exatos.
    Se lang != en, tenta encontrar uma impressão naquele idioma via oracle_id.
    Se não achar, retorna inglês com lang_fallback=True.
    Ex: /api/card-by-set/pip/325  ou  /api/card-by-set/40k/86★
    """
    lang = request.args.get("lang", "en").strip() or "en"

    r = scryfall(f"{SCRYFALL}/cards/{set_code.lower()}/{number}")
    if not r.ok:
        return jsonify({"error": f"Carta não encontrada: ({set_code}) {number}"}), 404
    c = r.json()

    if lang != "en":
        # Tenta encontrar impressão no idioma solicitado via oracle_id
        oracle_id = c.get("oracle_id", "")
        if oracle_id:
            r2 = scryfall(
                f"{SCRYFALL}/cards/search",
                q=f'oracleid:"{oracle_id}" lang:{lang}',
                order="released",
                unique="prints",
            )
            if r2.ok:
                prints = r2.json().get("data", [])
                lang_prints = [p for p in prints if p.get("lang") == lang]
                if lang_prints:
                    return jsonify(card_data(lang_prints[0]))
        # Não encontrou no idioma — usa inglês com indicador de fallback
        data = card_data(c)
        # Garante inglês: se a carta retornada não for en, busca impressão en
        if c.get("lang", "en") != "en":
            oracle_id = c.get("oracle_id", "")
            if oracle_id:
                r3 = scryfall(
                    f"{SCRYFALL}/cards/search",
                    q=f'oracleid:"{oracle_id}" lang:en',
                    order="released",
                    unique="prints",
                )
                if r3.ok:
                    en_prints = [p for p in r3.json().get("data", []) if p.get("lang") == "en"]
                    if en_prints:
                        data = card_data(en_prints[0])
        data["lang_fallback"] = True
        return jsonify(data)

    # Idioma inglês: comportamento original
    # Se não for inglês, busca a impressão EN pelo oracle_id
    if c.get("lang", "en") != "en":
        oracle_id = c.get("oracle_id", "")
        if oracle_id:
            r2 = scryfall(
                f"{SCRYFALL}/cards/search",
                q=f'oracleid:"{oracle_id}" lang:en',
                order="released",
                unique="prints",
            )
            if r2.ok:
                prints = r2.json().get("data", [])
                en_prints = [p for p in prints if p.get("lang") == "en"]
                if en_prints:
                    c = en_prints[0]  # impressão EN mais recente

    return jsonify(card_data(c))


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400
    f   = request.files["file"]
    ext = Path(f.filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        return jsonify({"error": "Formato não suportado (use JPG/PNG/WEBP)"}), 400
    uid  = str(uuid.uuid4())
    dest = UPLOAD_DIR / f"{uid}{ext}"
    f.save(str(dest))
    return jsonify({
        "id":    uid,
        "name":  f.filename,
        "path":  str(dest),
        "thumb": f"/api/thumb/{uid}{ext}",
        "png":   "",           # sem URL Scryfall
        "type":  "upload",
    })


@app.route("/api/thumb/<filename>")
def thumb(filename: str):
    p = UPLOAD_DIR / filename
    if not p.exists():
        abort(404)
    return send_file(str(p))


@app.route("/api/generate", methods=["POST"])
def generate():
    data      = request.get_json(silent=True) or {}
    card_list = data.get("cards", [])
    if not card_list:
        return jsonify({"error": "Lista de cartas vazia"}), 400

    # Separa cartas normais e DFCs (frente e verso)
    normal_paths: list[Path]        = []
    dfc_fronts:   list[Path]        = []
    dfc_backs:    list[Path]        = []

    for entry in card_list:
        qty  = max(1, min(int(entry.get("qty", 1)), 20))
        name = entry.get("name", "?")

        if entry.get("type") == "upload":
            p = Path(entry.get("path", ""))
            if not p.exists():
                return jsonify({"error": f"Arquivo não encontrado: {name}"}), 400
            normal_paths.extend([p] * qty)
            continue

        png_url = entry.get("png", "")
        if not png_url:
            return jsonify({"error": f"Sem imagem PNG para: {name}"}), 400

        try:
            front_path = download_png(png_url)
        except Exception as e:
            return jsonify({"error": f"Erro ao baixar {name}: {e}"}), 502

        if entry.get("is_dfc") and entry.get("back_png"):
            try:
                back_path = download_png(entry["back_png"])
            except Exception as e:
                return jsonify({"error": f"Erro ao baixar verso de {name}: {e}"}), 502
            for _ in range(qty):
                dfc_fronts.append(front_path)
                dfc_backs.append(back_path)
        else:
            normal_paths.extend([front_path] * qty)

    if not normal_paths and not dfc_fronts:
        return jsonify({"error": "Nenhuma imagem para gerar PDF"}), 400

    logo      = LOGO_PATH if LOGO_PATH.exists() else None
    pdf_files: dict[str, bytes] = {}          # nome → conteúdo binário

    # ── PDF principal (cartas normais) ────────────────────────────────────────
    if normal_paths:
        doc = fitz.open()
        for start in range(0, len(normal_paths), CARDS_PER_PAGE):
            build_page(doc, normal_paths[start : start + CARDS_PER_PAGE], logo)
        buf = io.BytesIO()
        doc.save(buf, garbage=4, deflate=True)
        pdf_files["deck.pdf"] = buf.getvalue()

    # ── PDF frente/verso (DFCs) — duplex-ready ────────────────────────────────
    if dfc_fronts:
        dfc_doc = build_dfc_pdf(dfc_fronts, dfc_backs, logo)
        buf = io.BytesIO()
        dfc_doc.save(buf, garbage=4, deflate=True)
        pdf_files["dfc_frente_verso.pdf"] = buf.getvalue()

    # ── Resposta ──────────────────────────────────────────────────────────────
    if len(pdf_files) == 1:
        name, content = next(iter(pdf_files.items()))
        return send_file(
            io.BytesIO(content),
            as_attachment=True,
            download_name=name,
            mimetype="application/pdf",
        )

    # Dois PDFs → ZIP
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in pdf_files.items():
            zf.writestr(name, content)
    zip_buf.seek(0)
    return send_file(
        zip_buf,
        as_attachment=True,
        download_name="deck_completo.zip",
        mimetype="application/zip",
    )


@app.route("/api/import-deck-url", methods=["POST"])
def import_deck_url():
    """
    Importa cartas de uma URL de deck externo.
    Suporta: Moxfield, Archidekt.
    Retorna lista de {qty, name, set, number} para a fila de importação.
    """
    data = request.get_json(silent=True) or {}
    url  = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL não fornecida"}), 400

    # ── Moxfield ─────────────────────────────────────────────────────────────
    mox = re.search(r"moxfield\.com/decks/([A-Za-z0-9_-]+)", url)
    if mox:
        deck_id = mox.group(1)
        r = scryfall(f"https://api2.moxfield.com/v2/decks/all/{deck_id}")
        if not r.ok:
            return jsonify({"error": f"Moxfield: deck não encontrado ({deck_id})"}), 404
        mox_data = r.json()
        cards = []
        for section in ("mainboard", "sideboard", "commanders", "companion"):
            for entry in (mox_data.get(section) or {}).values():
                c = entry.get("card", {})
                cards.append({
                    "qty":    entry.get("quantity", 1),
                    "name":   c.get("name", ""),
                    "set":    (c.get("set") or "").upper(),
                    "number": str(c.get("collectorNumber", "") or ""),
                })
        return jsonify({"source": "moxfield", "name": mox_data.get("name", "Deck"), "cards": cards})

    # ── Archidekt ─────────────────────────────────────────────────────────────
    arch = re.search(r"archidekt\.com/decks?/(\d+)", url)
    if arch:
        deck_id = arch.group(1)
        r = scryfall(f"https://archidekt.com/api/decks/{deck_id}/small/")
        if not r.ok:
            return jsonify({"error": f"Archidekt: deck não encontrado ({deck_id})"}), 404
        arch_data = r.json()
        cards = []
        for card in arch_data.get("cards", []):
            cats = card.get("categories", [])
            if "Maybeboard" in cats:
                continue
            oracle   = card.get("card", {}).get("oracleCard", {})
            editions = card.get("card", {}).get("editions", [{}])
            ed       = editions[0] if editions else {}
            cards.append({
                "qty":    card.get("quantity", 1),
                "name":   oracle.get("name", ""),
                "set":    (ed.get("set") or "").upper(),
                "number": str(ed.get("collectorNumber", "") or ""),
            })
        return jsonify({
            "source": "archidekt",
            "name":   arch_data.get("name", "Deck"),
            "cards":  cards,
        })

    return jsonify({"error": "URL não reconhecida. Suporta: Moxfield, Archidekt"}), 400


@app.route("/api/proxy-image", methods=["POST"])
def proxy_image():
    """
    Baixa uma imagem de qualquer URL pública e salva como upload local.
    Usado para cartas custom do MTGBuilder ou outros sites.
    """
    data = request.get_json(silent=True) or {}
    image_url = data.get("url", "").strip()
    card_name = data.get("name", "Carta custom").strip() or "Carta custom"
    if not image_url:
        return jsonify({"error": "URL não fornecida"}), 400
    if not image_url.startswith(("http://", "https://")):
        return jsonify({"error": "URL inválida (use http:// ou https://)"}), 400

    try:
        r = req.get(image_url, timeout=20, headers=HEADERS)
        r.raise_for_status()
        ct  = r.headers.get("content-type", "")
        ext = ".jpg"
        if "png"  in ct: ext = ".png"
        elif "webp" in ct: ext = ".webp"
        uid  = str(uuid.uuid4())
        dest = UPLOAD_DIR / f"{uid}{ext}"
        dest.write_bytes(r.content)
        return jsonify({
            "id":    uid,
            "name":  card_name,
            "path":  str(dest),
            "thumb": f"/api/thumb/{uid}{ext}",
            "png":   "",
            "type":  "upload",
        })
    except Exception as e:
        return jsonify({"error": f"Erro ao baixar imagem: {e}"}), 502


COCKATRICE_DIR = Path(r"C:\Users\eep0x10\AppData\Local\Cockatrice\Cockatrice\decks")


@app.route("/api/card-info")
def card_info():
    """Busca type_line + imagens por nome exato (para enriquecer cartas sem type_line)."""
    name = request.args.get("name", "").strip()
    lang = request.args.get("lang", "en").strip() or "en"
    if not name:
        return jsonify({"error": "Nome obrigatório"}), 400
    r = scryfall(f"{SCRYFALL}/cards/named", exact=name, lang=lang)
    if not r.ok:
        # Fallback: busca fuzzy
        r = scryfall(f"{SCRYFALL}/cards/named", fuzzy=name)
        if not r.ok:
            return jsonify({"error": f"Carta não encontrada: {name}"}), 404
    return jsonify(card_data(r.json()))


@app.route("/api/cockatrice/decks")
def cockatrice_decks():
    """Lista todos os arquivos .cod no diretório Cockatrice."""
    if not COCKATRICE_DIR.exists():
        return jsonify({"error": "Diretório Cockatrice não encontrado", "decks": []}), 200
    decks = []
    for f in sorted(COCKATRICE_DIR.glob("*.cod")):
        try:
            tree = ET.parse(str(f))
            root = tree.getroot()
            name_el = root.find("deckname")
            deck_name = (name_el.text or "").strip() if name_el is not None else ""
            if not deck_name:
                deck_name = f.stem
            # Conta total de cartas no main
            main_zone = root.find(".//zone[@name='main']")
            total = sum(int(c.get("number", 1)) for c in (main_zone or []))
            decks.append({
                "filename": f.name,
                "name":     deck_name,
                "total":    total,
            })
        except Exception:
            decks.append({"filename": f.name, "name": f.stem, "total": 0})
    return jsonify({"decks": decks})


@app.route("/api/cockatrice/deck/<path:filename>")
def cockatrice_read(filename: str):
    """Lê e parseia um arquivo .cod, retorna lista {name, qty, zone}."""
    p = COCKATRICE_DIR / filename
    if not p.exists() or p.suffix != ".cod":
        return jsonify({"error": "Arquivo não encontrado"}), 404
    try:
        tree = ET.parse(str(p))
        root = tree.getroot()
        name_el = root.find("deckname")
        deck_name = (name_el.text or "").strip() if name_el is not None else p.stem
        cards = []
        for zone in root.findall("zone"):
            zone_name = zone.get("name", "main")
            for card in zone.findall("card"):
                cards.append({
                    "name": card.get("name", ""),
                    "qty":  int(card.get("number", 1)),
                    "zone": zone_name,
                })
        return jsonify({"name": deck_name or p.stem, "filename": filename, "cards": cards})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cockatrice/save", methods=["POST"])
def cockatrice_save():
    """
    Salva o deck atual em formato .cod.
    Body: { filename: "nome.cod", deckname: "Nome", cards: [{name, qty, zone}] }
    """
    data     = request.get_json(silent=True) or {}
    filename = data.get("filename", "").strip()
    deckname = data.get("deckname", "").strip()
    cards    = data.get("cards", [])

    if not filename:
        return jsonify({"error": "filename obrigatório"}), 400
    if not filename.endswith(".cod"):
        filename += ".cod"
    # Segurança: não permitir path traversal
    p = (COCKATRICE_DIR / Path(filename).name)
    if not COCKATRICE_DIR.exists():
        return jsonify({"error": "Diretório Cockatrice não encontrado"}), 400

    root = ET.Element("cockatrice_deck", version="1")
    ET.SubElement(root, "deckname").text = deckname
    ET.SubElement(root, "comments").text = ""

    # Agrupa por zona
    zones: dict[str, list] = {}
    for c in cards:
        z = c.get("zone", "main")
        zones.setdefault(z, []).append(c)

    for zone_name, zone_cards in zones.items():
        zone_el = ET.SubElement(root, "zone", name=zone_name)
        for c in zone_cards:
            ET.SubElement(zone_el, "card",
                          number=str(c.get("qty", 1)),
                          name=c.get("name", ""))

    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    with open(str(p), "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="unicode", xml_declaration=False)

    return jsonify({"ok": True, "saved": p.name})


if __name__ == "__main__":
    print("MTG Craft rodando em http://localhost:5001")
    # use_reloader=False evita problema de SSL no child process do Werkzeug reloader (WSL2)
    app.run(host="0.0.0.0", port=5001, debug=True, use_reloader=False)
