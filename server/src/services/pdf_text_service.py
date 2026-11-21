"""
PDF text, page by page: the embedded text layer where it can be trusted,
OCR with a local Ollama vision model (Qwen3-VL etc.) everywhere else.

A born-digital PDF (InDesign, LaTeX, Word) already carries the exact text,
diacritics included; reading it is instant and makes no OCR errors. A scan has
no text layer, or an invisible OCR layer of unknown quality. The choice is made
per page, because one PDF can hold both (a scanned plate in a digital article).

Nothing runs on the whole document before a check: a plan is made, one or two
sample pages are processed with it, and a reviewer (Claude, through the MCP
server) compares page image and proposed text and approves the plan. Only then
does the batch run, locally.

Embedded text is cleaned:
  - raised small spans become superscripts (footnote numbers, determinatives),
    lowered small spans subscripts (du3 -> du with subscript 3);
  - TeX spacing accents are put back on their letter by position (H + breve below);
  - small-caps fonts are uppercased (sign names: tar -> TAR);
  - typographic ligatures become plain letters, soft hyphens at line ends "-";
  - glyphs without a Unicode mapping are marked [?] and reported, never guessed.
Line breaks and end-of-line hyphens stay as printed, as in OCR output.

Results go to one text file per page plus manifest.json, so a failed or
interrupted run can be resumed and single pages rerun.
"""

import base64
import io
import json
import logging
import os
import re
import threading
import time
import unicodedata
import uuid
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

DEFAULT_DPI = 300
DEFAULT_PROMPT = "exact_copy"
# First installed one wins; general models before ones fine-tuned on one source (AHw).
PREFERRED_OCR_MODELS = ["qwen3-vl:8b", "qwen3-vl:4b", "qwen3-vl:2b", "qwen3-vl", "glm-ocr"]
LAYOUTS = ("'page' (whole page), 'columns' (split at the gutter), 'lines' (columns, then each printed "
           "line found by Kraken, read one by one) or 'yolo:<model>' (BEn YOLO regions)")

# Code points are written as chr() so the source holds no invisible characters.
_FFFD = chr(0xFFFD)
_PUA = (chr(0xE000), chr(0xF8FF))
_SOFT_HYPHEN = chr(0x00AD)

# ── Embedded text ──────────────────────────────────────────────────────

_LIGATURES = {chr(0xFB00): "ff", chr(0xFB01): "fi", chr(0xFB02): "fl", chr(0xFB03): "ffi",
              chr(0xFB04): "ffl", chr(0xFB05): "st", chr(0xFB06): "st"}
_SUP = str.maketrans(
    "0123456789+-=()abcdefghijklmnoprstuvwxyzABDEGHIJKLMNOPRTUVW",
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ")
_SUB = str.maketrans("0123456789x+-=()", "₀₁₂₃₄₅₆₇₈₉ₓ₊₋₌₍₎")
_SUP_OK = set("0123456789+-=()abcdefghijklmnoprstuvwxyzABDEGHIJKLMNOPRTUVW")
_SUB_OK = set("0123456789x+-=()")
_VOWELS = set("aeiouyäöüáàâāăéèêēĕíìîīĭóòôōŏúùûūŭ")
# Small-caps font names: "AndronMegaCorpus-SC700", "...-SCReg", "TextraLT-MediumSC", "...SmallCaps"
_SMALL_CAPS_FONT = re.compile(r"(?i)(sc\d{3}|screg|smallcap|[a-z]sc$|-sc\b|caps\b)")
# The characters worth checking in a sample: Assyriological diacritics, sub- and superscripts
SPECIAL_CHARS = set("šṣṭḫŠṢṬḪāēīūĀĒĪŪâêîûÂÊÎÛ₀₁₂₃₄₅₆₇₈₉ₓ⁰¹²³⁴⁵⁶⁷⁸⁹ᵈᵍⁱˢᵐᶠᵏ")


def _script(text: str, kind: str) -> str:
    """Raise or lower a span; spans with letters lacking a Unicode form (š) get ^{..} / _{..}."""
    core = text.strip()
    if not core:
        return text
    ok, table, mark = (_SUP_OK, _SUP, "^") if kind == "sup" else (_SUB_OK, _SUB, "_")
    lead, trail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()):]
    if set(core) <= ok:
        return lead + core.translate(table) + trail
    return f"{lead}{mark}{{{core}}}{trail}"


# Spacing accents as TeX (dvips) and some other producers emit them: a separate glyph
# placed over or under the letter. spacing accent -> (combining mark above, below)
_SPACING_ACCENTS = {
    chr(0x02D8): (chr(0x0306), chr(0x032E)),  # breve: Ḫ is H + breve below
    chr(0x02C7): (chr(0x030C), chr(0x032C)),  # caron: š
    chr(0x00AF): (chr(0x0304), chr(0x0331)),  # macron: ā
    chr(0x02C9): (chr(0x0304), chr(0x0331)),
    chr(0x02D9): (chr(0x0307), chr(0x0323)),  # dot: ṣ ṭ (below), İ (above)
    chr(0x00B4): (chr(0x0301), None), chr(0x02CA): (chr(0x0301), None),
    chr(0x0060): (chr(0x0300), None), chr(0x02CB): (chr(0x0300), None),
    chr(0x00A8): (chr(0x0308), chr(0x0324)),
    chr(0x005E): (chr(0x0302), chr(0x032D)), chr(0x02C6): (chr(0x0302), chr(0x032D)),
    chr(0x02DA): (chr(0x030A), chr(0x0325)),
    chr(0x02DC): (chr(0x0303), chr(0x0330)),
    chr(0x00B8): (None, chr(0x0327)), chr(0x02DB): (None, chr(0x0328)),
}
# A breve, caron, dot, ring or ogonek glyph that sits on no letter is a mis-mapped
# symbol, not an accent (a TeX math font gave the dot for "±").
_ORPHAN_ACCENTS = {chr(c) for c in (0x02D8, 0x02C7, 0x02D9, 0x02DA, 0x02DB)}


def _attach_accents(chars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn a spacing accent glyph lying over/under the next or previous letter into a combining mark."""
    out = [dict(c) for c in chars]
    drop = set()
    for i, ch in enumerate(out):
        marks = _SPACING_ACCENTS.get(ch["c"])
        if not marks:
            continue
        ax0, ay0, ax1, ay1 = ch["bbox"]
        acx, acy = (ax0 + ax1) / 2, (ay0 + ay1) / 2
        for j in (i + 1, i - 1):
            if not (0 <= j < len(out)) or j in drop or not out[j]["c"][:1].isalpha():
                continue
            lx0, ly0, lx1, ly1 = out[j]["bbox"]
            if not (lx0 - 1 <= acx <= lx1 + 1):
                continue
            mark = marks[1] if acy > (ly0 + ly1) / 2 else marks[0]
            if mark:
                out[j]["c"] = out[j]["c"] + mark
                drop.add(i)
            break
    return [c for k, c in enumerate(out) if k not in drop]


def _is_bad(c: str) -> bool:
    return c == _FFFD or _PUA[0] <= c <= _PUA[1] or (unicodedata.category(c) == "Cc" and c not in "\n\t")


def _line_text(line: Dict[str, Any], undecoded: Dict[str, int]) -> str:
    # rawdict gives single characters with positions; rebuild each span's text after fixing accents
    flat = [(si, c) for si, s in enumerate(line["spans"]) for c in s.get("chars", [])]
    fixed = _attach_accents([c for _, c in flat])
    # fixed keeps the order minus the merged accents: walk both to give each span its text back
    texts: Dict[int, List[str]] = {}
    fi = 0
    for si, c in flat:
        if fi < len(fixed) and fixed[fi]["origin"] == c["origin"] and fixed[fi]["bbox"] == c["bbox"]:
            texts.setdefault(si, []).append(fixed[fi]["c"])
            fi += 1
    for si, s in enumerate(line["spans"]):
        s["text"] = "".join(texts.get(si, []))
    spans = [s for s in line["spans"] if s["text"]]
    if not spans:
        return ""
    # A line of a figure whose font has no Unicode mapping: nothing readable to keep.
    joined = "".join(s["text"] for s in spans).replace(" ", "")
    if joined and sum(map(_is_bad, joined)) / len(joined) > 0.5:
        return ""
    for s in spans:
        # Glyphs inside the running text that cannot be decoded: mark them, never guess.
        if any(_is_bad(c) or c in _ORPHAN_ACCENTS for c in s["text"]):
            n = sum(1 for c in s["text"] if _is_bad(c) or c in _ORPHAN_ACCENTS)
            undecoded[s["font"]] = undecoded.get(s["font"], 0) + n
            s["text"] = "".join("[?]" if (_is_bad(c) or c in _ORPHAN_ACCENTS) else c for c in s["text"])
        if _SMALL_CAPS_FONT.search(s["font"]):
            s["text"] = s["text"].upper()
    # The line's main font: the size carrying most characters, and its baseline.
    weight: Dict[float, int] = {}
    for s in spans:
        weight[round(s["size"], 1)] = weight.get(round(s["size"], 1), 0) + len(s["text"].strip())
    main_size = max(weight, key=weight.get)
    main = [s for s in spans if round(s["size"], 1) == main_size]
    baseline = sorted(s["origin"][1] for s in main)[len(main) // 2]

    # A letter the small-caps font lacks (ḫ, ṭ) is often set from another font as a small
    # lowercase letter glued to the small caps (GIŠ.ḪUR printed as "giš." + "ḫ" + "ur").
    sc = [bool(_SMALL_CAPS_FONT.search(s["font"])) for s in spans]
    for i, s in enumerate(spans):
        t = s["text"]
        if sc[i] or not t.strip() or t != t.strip() or t != t.lower() or s["size"] >= 0.85 * main_size:
            continue
        glued_before = i > 0 and sc[i - 1] and not spans[i - 1]["text"][-1:].isspace()
        glued_after = i + 1 < len(spans) and sc[i + 1] and not spans[i + 1]["text"][:1].isspace()
        if glued_before or glued_after:
            s["text"] = t.upper()

    out = []
    for s in spans:
        text = s["text"]
        small = s["size"] < 0.85 * main_size
        rise = baseline - s["origin"][1]  # PDF y grows downwards
        if (s["flags"] & 1 or (small and rise > 0.15 * main_size)) and s["size"] < main_size:
            text = _script(text, "sup")
        elif small and rise < -0.1 * main_size:
            text = _script(text, "sub")
        out.append(text)
    return "".join(out)


def embedded_lines(page: "fitz.Page") -> Tuple[List[List[Tuple[str, "fitz.Rect"]]], List[str]]:
    """The page's text layer, cleaned, as blocks of (line text, line box in page points);
    and warnings (glyphs that could not be decoded)."""
    flags = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP  # no PRESERVE_LIGATURES
    undecoded: Dict[str, int] = {}
    blocks = []
    for b in page.get_text("rawdict", flags=flags)["blocks"]:
        if b.get("type") != 0:
            continue
        lines = []
        for l in b["lines"]:
            text = _line_text(l, undecoded).rstrip()
            if not text.strip():
                continue
            for lig, plain in _LIGATURES.items():
                text = text.replace(lig, plain)
            # soft hyphen: printed as "-" where the line breaks, invisible elsewhere
            if text.endswith(_SOFT_HYPHEN):
                text = text[:-1] + "-"
            # no-break spaces become plain ones: otherwise "S. 12" is not found when searched in BEn
            text = unicodedata.normalize("NFC", text.replace(_SOFT_HYPHEN, "").replace(chr(0xA0), " "))
            lines.append((text, fitz.Rect(l["bbox"])))
        if lines:
            blocks.append(lines)
    warnings = []
    if undecoded:
        fonts = ", ".join(f"{f} ({n})" for f, n in sorted(undecoded.items(), key=lambda kv: -kv[1]))
        warnings.append(f"{sum(undecoded.values())} glyphs without Unicode mapping marked [?] "
                        f"(fonts: {fonts}); likely math symbols or Greek; check the page image")
    return blocks, warnings


def embedded_text(page: "fitz.Page") -> Tuple[str, List[str]]:
    """The page's text layer, cleaned (lines as printed, blocks separated by a blank line)."""
    blocks, warnings = embedded_lines(page)
    return "\n\n".join("\n".join(t for t, _ in b) for b in blocks), warnings


# ── Is the text layer usable? ──────────────────────────────────────────

def analyse_page(page: "fitz.Page") -> Dict[str, Any]:
    """Decide 'embedded', 'ocr' or 'empty' for one page, with the reason."""
    text = page.get_text()
    chars = [c for c in text if not c.isspace()]
    n = len(chars)
    area = abs(page.rect) or 1
    image_cover = max((abs(fitz.Rect(i["bbox"]) & page.rect) / area for i in page.get_image_info()), default=0.0)

    info: Dict[str, Any] = {"page": page.number + 1, "chars": n, "image_cover": round(image_cover, 2)}

    def verdict(v: str, reason: str) -> Dict[str, Any]:
        info.update(route=v, reason=reason)
        return info

    if n < 30:
        if image_cover > 0.5:
            return verdict("ocr", "no text layer; the page is an image (scan)")
        return verdict("empty" if n == 0 else "embedded", "blank page" if n == 0 else "very little text, no page image")

    try:  # text drawn invisibly over a scan = an OCR layer someone added, quality unknown
        trace = page.get_texttrace()
        total = sum(len(s["chars"]) for s in trace) or 1
        hidden = sum(len(s["chars"]) for s in trace if s.get("type") == 3 or s.get("opacity", 1) == 0)
        info["invisible"] = round(hidden / total, 2)
        if hidden / total > 0.5:
            return verdict("ocr", "text layer is invisible OCR text laid over a scan")
    except Exception:
        pass

    # Unmapped glyphs: harmless when whole lines are unreadable (labels inside a vector
    # figure, dropped on extraction); fatal when they sit inside the running text.
    bad_total = bad_body = body = 0
    for line in text.splitlines():
        cs = [c for c in line if not c.isspace()]
        b = sum(map(_is_bad, cs))
        bad_total += b
        if cs and b / len(cs) <= 0.5:
            bad_body += b
            body += len(cs)
    info["bad_chars"] = bad_total
    if body == 0 or bad_body / body > 0.01:
        return verdict("ocr", f"{bad_total} unmapped glyphs in the text (font without Unicode mapping)")

    # Garbled encodings come out as symbol soup or as letter strings that are not words.
    # Count only letters against symbols: dot leaders, digits and punctuation are normal
    # in contents pages, tables and bibliographies.
    letters = sum(1 for c in chars if c.isalpha())
    symbols = sum(1 for c in chars if unicodedata.category(c).startswith("S"))
    words = re.findall(r"[^\W\d_]{3,}", text)
    voweled = sum(1 for w in words if any(c in _VOWELS for c in w.lower()))
    if words:
        info["word_ratio"] = round(voweled / len(words), 2)
    if letters < 2 * symbols or (len(words) >= 15 and voweled / len(words) < 0.5):
        return verdict("ocr", "text layer looks garbled (symbols, or letter strings that are not words)")

    note = "born-digital text layer"
    if bad_total:
        note += f"; {bad_total} unreadable glyphs in figures left out"
    if image_cover > 0.85:
        note = "real text over a full-page image; check against the scan if in doubt"
    return verdict("embedded", note)


def inspect_pdf(path: str) -> Dict[str, Any]:
    with fitz.open(path) as doc:
        pages = [analyse_page(p) for p in doc]
        meta = {k: (doc.metadata or {}).get(k) for k in ("producer", "creator", "title")}
    by_route: Dict[str, List[int]] = {}
    by_reason: Dict[tuple, List[int]] = {}
    for p in pages:
        by_route.setdefault(p["route"], []).append(p["page"])
        if p["route"] != "embedded":
            by_reason.setdefault((p["route"], p["reason"]), []).append(p["page"])
    # grouped by reason with page ranges: a 500-page book stays a few lines long
    return {
        "path": os.path.abspath(path),
        "page_count": len(pages),
        "metadata": meta,
        "routes": {k: _ranges(v) for k, v in by_route.items()},
        "not_embedded": [{"pages": _ranges(v), "route": r, "reason": why} for (r, why), v in by_reason.items()],
    }


# ── Layout: which parts of a page go to OCR, in which order ────────────

def _column_gutter(dark, y0: Optional[int] = None, y1: Optional[int] = None) -> Tuple[int, float]:
    """The gutter in an ink mask (100 dpi): the x in the middle third where text rows most
    often have ink on both sides but none in between, and the share of those rows that
    do have ink in between (0 = a clean gutter, about 0.5 and more = one column).

    Only rows with text right and left of x count: rows of a figure, or a blank middle
    in a diagram, say nothing about columns. The window in between is 9 px (~6 pt):
    wider than a word space, narrower than any gutter."""
    import numpy as np
    h, w = dark.shape
    body = dark[int(h * 0.1) if y0 is None else y0: int(h * 0.92) if y1 is None else y1].astype(np.int32)
    cs = np.concatenate([np.zeros((body.shape[0], 1), np.int32), body.cumsum(axis=1)], axis=1)
    half, flank = 4, 50
    xs = range(max(int(w * 0.35), flank), min(int(w * 0.65), w - flank))
    vs = []
    for x in xs:
        center = cs[:, x + half + 1] - cs[:, x - half] > 0
        both = (cs[:, x - half - 1] - cs[:, x - flank] > 0) & (cs[:, x + flank] - cs[:, x + half + 2] > 0)
        n = int(both.sum())
        vs.append(float((center & both).sum()) / n if n >= 20 else 1.0)
    if not vs:
        return w // 2, 1.0
    vs = np.array(vs)
    best = float(vs.min())
    # the middle of the stretch of (nearly) best x around the minimum: a clean gutter is
    # many pixels wide, and its edge is no place to cut
    k = lo = hi = int(vs.argmin())
    while lo > 0 and vs[lo - 1] <= best + 0.02:
        lo -= 1
    while hi < len(vs) - 1 and vs[hi + 1] <= best + 0.02:
        hi += 1
    return xs[(lo + hi) // 2], best


def _crossing_share(dark, xs, y0: int, y1: int) -> float:
    """Of the rows y0..y1 with text right and left of the gutter (xs[row - y0] = its x in
    that row), the share with ink in the gutter itself: 0 for a clean gutter."""
    import numpy as np
    half, flank = 4, 50
    w = dark.shape[1]
    hits = n = 0
    for y, x in zip(range(y0, y1), xs):
        x = int(min(max(x, flank), w - flank - 1))
        row = dark[y]
        if row[x - flank:x - half - 1].any() and row[x + half + 2:x + flank].any():
            n += 1
            hits += bool(row[x - half:x + half + 1].any())
    return hits / n if n >= 20 else 1.0


def _drop_vertical_rules(dark, min_len: int) -> None:
    """Remove vertical strokes longer than any letter (a printed column rule, also when the
    scan is a little skewed) from the middle third of an ink mask, in place."""
    import numpy as np
    h, w = dark.shape
    for c in range(int(w * 0.3), int(w * 0.7)):
        col = dark[:, c]
        if col.sum() < min_len:
            continue
        edges = np.flatnonzero(np.diff(np.concatenate(([0], col.astype(np.int8), [0]))))
        for start, end in zip(edges[::2], edges[1::2]):
            if end - start >= min_len:
                col[start:end] = False


def _reading_order(regions: List[Dict[str, Any]], page_rect: "fitz.Rect") -> List[Dict[str, Any]]:
    """Order boxes as a reader would. Full-width boxes, and rows of short boxes on one line
    across both halves (a running header: guide word, page number, guide word), split the
    page into bands; inside a band, the left column top to bottom, then the right column."""
    mid = page_rect.x0 + page_rect.width / 2
    left_half = lambda r: (r["rect"].x0 + r["rect"].x1) / 2 < mid
    short = lambda r: r["rect"].height < 0.05 * page_rect.height

    def same_line(a, b):
        overlap = min(a["rect"].y1, b["rect"].y1) - max(a["rect"].y0, b["rect"].y0)
        return overlap > 0.5 * min(a["rect"].height, b["rect"].height)

    # rows: short boxes sharing a line with a short box in the other half
    rows: List[List[Dict[str, Any]]] = []
    in_row = set()
    for a in regions:
        if id(a) in in_row or not short(a):
            continue
        row = [b for b in regions if short(b) and (b is a or same_line(a, b))]
        if len({left_half(b) for b in row}) == 2:
            rows.append(sorted(row, key=lambda b: b["rect"].x0))
            in_row.update(id(b) for b in row)
    items = [("row", min(b["rect"].y0 for b in row), row) for row in rows]
    items += [("wide" if r["rect"].width > 0.6 * page_rect.width else "box", r["rect"].y0, [r])
              for r in regions if id(r) not in in_row]

    ordered, band = [], []

    def flush():
        ordered.extend(sorted((r for r in band if left_half(r)), key=lambda r: r["rect"].y0))
        ordered.extend(sorted((r for r in band if not left_half(r)), key=lambda r: r["rect"].y0))
        band.clear()

    for kind, _, rs in sorted(items, key=lambda it: it[1]):
        if kind == "box":
            band.extend(rs)
        else:
            flush()
            ordered.extend(rs)
    flush()
    return ordered


def _yolo_regions(page: "fitz.Page", model_name: str, confidence: float = 0.25) -> List[Dict[str, Any]]:
    """Regions found by one of BEn's YOLO layout models, in page coordinates."""
    from clients.yolo_training_client import yolo_training_client
    dpi = 150
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
    result = yolo_training_client.predict(base64.b64encode(pix.tobytes("png")).decode(),
                                          model_name=model_name or "default", confidence=confidence)
    scale = 72 / dpi
    regions = []
    for d in result.get("detections", []):
        b = d["bbox"]
        x0, y0 = page.rect.x0 + b["x"] * scale, page.rect.y0 + b["y"] * scale
        rect = fitz.Rect(x0, y0, x0 + b["width"] * scale, y0 + b["height"] * scale)
        regions.append({"rect": rect, "label": d["class_name"], "confidence": d["confidence"]})
    return regions


_blla_lock = threading.Lock()


def _blla_lines(page: "fitz.Page", dpi: int = 200) -> List[Tuple["fitz.Rect", List[Tuple[float, float]]]]:
    """Text lines found by Kraken's neural line detector (blla): (box, outline polygon),
    both in page points. The outline matters: a plain box around a line also catches the
    ascenders and descenders of its neighbours, and the model then reads one and a half lines."""
    from PIL import Image
    from kraken import blla
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    with _blla_lock:
        try:
            import torch
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
            seg = blla.segment(img, device=device)
        except RuntimeError:  # GPU busy or out of memory (Ollama holds most of it): use the CPU
            seg = blla.segment(img, device="cpu")
    s = 72 / dpi
    out = []
    for line in seg.lines:
        pts = [(page.rect.x0 + x * s, page.rect.y0 + y * s) for x, y in (line.boundary or line.baseline)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        out.append((fitz.Rect(min(xs), min(ys), max(xs), max(ys)), pts))
    return out


def _gutter(page: "fitz.Page") -> Dict[str, Any]:
    """Whether the page has two columns, and where the gutter between them is.

    Returns the ink mask at 100 dpi ("dark": scanner borders and a printed column rule
    removed), the pixel columns of the gutter itself ("rule_free": ±1 px around it;
    justified text reaches right up to it), the whole empty strip between the columns
    ("gap"), "two_columns", pixels per point ("scale") and the gutter's x in points ("x")."""
    import numpy as np
    r = page.rect
    pix = page.get_pixmap(dpi=100, colorspace=fitz.csRGB)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].mean(axis=2)
    dark = gray < 128
    dark[dark.mean(axis=1) > 0.5, :] = False  # scanner borders
    dark[:, dark.mean(axis=0) > 0.5] = False
    # A rule between the columns (OLZ and many journals print one) is ink in the gutter on
    # every row; 0.18 inch of unbroken vertical ink is taller than any letter.
    _drop_vertical_rules(dark, min_len=18)
    gx, crossed = _column_gutter(dark)
    rule_free = list(range(max(0, gx - 1), min(pix.width, gx + 2)))
    body = dark[int(pix.height * 0.15): int(pix.height * 0.9)]
    two_columns = crossed < 0.45 and body.mean() > 0.005
    # the whole empty strip between the columns (a gap between two words of a centered
    # title can be wider than the ±1 px around the gutter's middle)
    lo = hi = gx
    while lo > 0 and body[:, lo - 1].mean() < 0.002:
        lo -= 1
    while hi < pix.width - 1 and body[:, hi + 1].mean() < 0.002:
        hi += 1
    gap = list(range(lo + 3, hi - 2)) or rule_free  # keep off the column edges
    s = pix.width / r.width
    # A skewed scan has a slanted gutter: measured in the upper and the lower half, it
    # gives the gutter's x at any height (a single x would put the last lines of the left
    # column across it).
    top, bottom = int(pix.height * 0.1), int(pix.height * 0.92)
    mid = (top + bottom) // 2
    xt, vt = _column_gutter(dark, top, mid)
    xb, vb = _column_gutter(dark, mid, bottom)
    slope = 0.0
    y_mid = (top + bottom) / 2
    if two_columns and vt < 0.45 and vb < 0.45 and abs(xt - xb) < 0.04 * pix.width             and abs((xt + xb) / 2 - gx) < 0.02 * pix.width:
        tilt = (xb - xt) / ((bottom - top) / 2)  # pixels of x per pixel of y
        # only if the slanted gutter is cleaner than the straight one: a centered heading
        # or a figure in one half can pull that half's estimate onto the text
        straight = _crossing_share(dark, [gx] * (bottom - top), top, bottom)
        slanted = _crossing_share(dark, [gx + tilt * (y - y_mid) for y in range(top, bottom)], top, bottom)
        if slanted < straight:
            slope = tilt

    def px_at(y_px: float) -> int:
        return int(round(gx + slope * (y_px - y_mid)))

    def x_at(y_pt: float) -> float:
        return r.x0 + px_at((y_pt - r.y0) * s) / s

    return {"dark": dark, "rule_free": rule_free, "gap": gap, "two_columns": two_columns,
            "scale": s, "x": r.x0 + gx / s, "x_at": x_at, "px_at": px_at}


def _column_layout(page: "fitz.Page") -> List[Dict[str, Any]]:
    """Two columns where the page has them, without cutting through what spans both.

    Text lines that put ink into the gutter (a centered title such as "No. 20  MS 1806
    Pls. L-LI", a running header, a full-width paragraph) are read as full-width bands;
    between them, the left column, then the right one. A page without a gutter is one region."""
    import numpy as np
    r = page.rect
    g = _gutter(page)
    if not g["two_columns"]:
        return [{"rect": fitz.Rect(r), "label": "page (one column)"}]
    dark, s = g["dark"], g["scale"]
    has_ink = dark.any(axis=1)
    gutter_ink = dark[:, g["gap"]].any(axis=1)
    # runs of rows with ink, separated by blank rows: one or more text lines each
    runs, y = [], 0
    while y < len(has_ink):
        if not has_ink[y]:
            y += 1
            continue
        y0 = y
        while y < len(has_ink) and has_ink[y]:
            y += 1
        # wide: ink in the gutter over a good part of the run's height (letters of a title
        # crossing it), not a few specks of a scan inside a run of column lines
        runs.append([y0, y, gutter_ink[y0:y].sum() >= max(2, 0.12 * (y - y0))])
    if not runs:
        return [{"rect": fitz.Rect(r), "label": "page (blank)"}]
    # consecutive runs of the same kind form a band; a band ends halfway into the blank between
    bands = [runs[0][:]]
    for y0, y1, wide in runs[1:]:
        if wide == bands[-1][2]:
            bands[-1][1] = y1
        else:
            cut = (bands[-1][1] + y0) // 2
            bands[-1][1] = cut
            bands.append([cut, y1, wide])
    # a strip of "two columns" no taller than two lines between full-width bands is centered
    # text whose word gaps happen to fall on the gutter (title pages, lists)
    line_h = 2.5 * 12 * s  # two and a half lines of 12 pt, in pixels
    k = 1
    while k < len(bands) - 1:
        if not bands[k][2] and bands[k - 1][2] and bands[k + 1][2] and bands[k][1] - bands[k][0] < line_h:
            bands[k - 1][1] = bands[k + 1][1]
            del bands[k:k + 2]
        else:
            k += 1
    bands[0][0], bands[-1][1] = 0, len(has_ink)
    out = []
    for y0, y1, wide in bands:
        top, bottom = r.y0 + y0 / s, min(r.y1, r.y0 + y1 / s)
        if wide:
            out.append({"rect": fitz.Rect(r.x0, top, r.x1, bottom), "label": "full width"})
        else:
            out.append({"rect": fitz.Rect(r.x0, top, g["x"], bottom), "label": "left column"})
            out.append({"rect": fitz.Rect(g["x"], top, r.x1, bottom), "label": "right column"})
    return out


def _line_layout(page: "fitz.Page") -> List[Dict[str, Any]]:
    """Columns, then lines: every printed line as its own region, in reading order.

    Lines come from Kraken blla on the whole page. If the page has two columns (an empty
    gutter), a detected line running across the empty gutter is split in two; a line
    with ink in the gutter (a running header) stays whole and is read before the columns
    below it. Specks and pen marks smaller than a text line are dropped.
    """
    r = page.rect
    lines = _blla_lines(page)
    if not lines:
        return [{"rect": fitz.Rect(r), "label": "page (no lines found)"}]

    g = _gutter(page)
    dark, two_columns, s, x_at = g["dark"], g["two_columns"], g["scale"], g["x_at"]

    def ink_in_gutter(rect: "fitz.Rect") -> bool:
        """One printed line across the gutter (a running header, a centered title), or a
        left and a right column line that blla joined? The blank around the gutter in this
        line's rows tells: a word space is at most ~4 pt, the gap between columns far wider."""
        y0, y1 = (int((v - r.y0) * s) for v in (rect.y0 + 0.2 * rect.height, rect.y1 - 0.2 * rect.height))
        ink = dark[max(0, y0):max(y0 + 1, y1), :].any(axis=0)
        gx = min(len(ink) - 1, max(0, g["px_at"]((y0 + y1) / 2)))
        if ink[gx]:
            return True
        lo = hi = gx
        while lo > 0 and not ink[lo - 1]:
            lo -= 1
        while hi < len(ink) - 1 and not ink[hi + 1]:
            hi += 1
        return (hi - lo + 1) < 8 * s

    pieces, outline = [], {}  # outline: id(piece) -> polygon of the detected line it comes from
    for rect, poly in lines:
        x_gutter = x_at((rect.y0 + rect.y1) / 2)
        if two_columns and rect.x0 < x_gutter - 2 < x_gutter + 2 < rect.x1 and not ink_in_gutter(rect):
            split = [fitz.Rect(rect.x0, rect.y0, x_gutter, rect.y1), fitz.Rect(x_gutter, rect.y0, rect.x1, rect.y1)]
        else:
            split = [rect]
        for p in split:
            pieces.append(p)
            outline[id(p)] = poly
    heights = sorted(p.height for p in pieces)
    h = heights[len(heights) // 2]
    pieces = [p for p in pieces if p.height > 0.4 * h and p.width > 2 * h]

    # The text block: where most lines start and end. Readers' notes in the margins lie
    # mostly outside it and are dropped.
    x0s, x1s = sorted(p.x0 for p in pieces), sorted(p.x1 for p in pieces)
    block = fitz.Rect(x0s[len(x0s) // 10] - h, r.y0, x1s[len(x1s) * 9 // 10] + h, r.y1)
    pieces = [p for p in pieces if abs(p & block) > 0.5 * abs(p)]

    def side(p):
        x_gutter = x_at((p.y0 + p.y1) / 2)
        if not two_columns or (p.x0 < x_gutter - 2 and p.x1 > x_gutter + 2):
            return "full"
        return "left" if (p.x0 + p.x1) / 2 < x_gutter else "right"

    def same_row(a, b):
        return min(a.y1, b.y1) - max(a.y0, b.y0) > 0.5 * min(a.height, b.height)

    # A full-width line and the pieces beside it on the same row (a running header:
    # page number, title, date) form one row, read left to right.
    full = [p for p in pieces if side(p) == "full"]
    rows = [sorted([f] + [p for p in pieces if p is not f and side(p) != "full" and same_row(f, p)],
                   key=lambda p: p.x0) for f in full]
    in_row = {id(p) for row in rows for p in row}

    ordered, band = [], []

    def flush():
        ordered.extend(sorted((p for p in band if side(p) == "left"), key=lambda p: p.y0))
        ordered.extend(sorted((p for p in band if side(p) == "right"), key=lambda p: p.y0))
        band.clear()

    items = [(row[0].y0, row) for row in rows] + [(p.y0, p) for p in pieces if id(p) not in in_row]
    for _, item in sorted(items, key=lambda it: it[0]):
        if isinstance(item, list):
            flush()
            ordered.extend(item)
        else:
            band.append(item)
    flush()
    label = lambda p: ("line (full)" if id(p) in in_row else f"line ({side(p)})") if two_columns else "line"
    return [{"rect": fitz.Rect(p) & r, "label": label(p), "polygon": outline[id(p)]} for p in ordered]


def _line_image(page_img, scale: float, origin: "fitz.Point", rect: "fitz.Rect", polygon) -> bytes:
    """PNG of one line: the page image inside the line's outline polygon, white elsewhere,
    cropped to the line's box (a box split at the gutter keeps its half of the outline)."""
    from PIL import Image, ImageDraw
    box = [int((rect.x0 - origin.x) * scale), int((rect.y0 - origin.y) * scale),
           int((rect.x1 - origin.x) * scale) + 1, int((rect.y1 - origin.y) * scale) + 1]
    crop = page_img.crop(box)
    mask = Image.new("L", crop.size, 0)
    ImageDraw.Draw(mask).polygon([((x - origin.x) * scale - box[0], (y - origin.y) * scale - box[1])
                                  for x, y in polygon], fill=255)
    out = Image.new("RGB", crop.size, (255, 255, 255))
    out.paste(crop, (0, 0), mask)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def page_regions(page: "fitz.Page", layout: str) -> List[Dict[str, Any]]:
    """The parts of the page sent to OCR one by one, in reading order."""
    r = page.rect
    if layout in ("page", "", None):
        return [{"rect": fitz.Rect(r), "label": "page"}]
    if layout == "columns":
        return _column_layout(page)
    if layout == "lines":
        return _line_layout(page)
    if layout.startswith("yolo"):
        model_name = layout.partition(":")[2]
        regions = _yolo_regions(page, model_name)
        if not regions:
            return [{"rect": fitz.Rect(r), "label": "page (YOLO found no regions)"}]
        return _reading_order(regions, r)
    raise ValueError(f"unknown layout {layout!r}; use {LAYOUTS}")


def page_preview(page: "fitz.Page", regions: Optional[List[Dict[str, Any]]] = None,
                 clip: Optional["fitz.Rect"] = None, long_side: int = 1568) -> bytes:
    """JPEG of the page (or a part of it) for a reviewer, with OCR regions drawn and numbered."""
    from PIL import Image, ImageDraw
    area = clip or page.rect
    dpi = int(max(36, min(600, long_side / (max(area.width, area.height) / 72))))
    pix = page.get_pixmap(dpi=dpi, clip=area, colorspace=fitz.csRGB)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    if regions and len(regions) > 1:
        draw = ImageDraw.Draw(img)
        s = dpi / 72
        for i, reg in enumerate(regions, 1):
            x0, y0, x1, y1 = [(v - o) * s for v, o in zip(reg["rect"], (area.x0, area.y0, area.x0, area.y0))]
            draw.rectangle([x0, y0, x1, y1], outline=(220, 30, 30), width=3)
            draw.rectangle([x0, y0, x0 + 34, y0 + 22], fill=(220, 30, 30))
            draw.text((x0 + 6, y0 + 4), str(i), fill=(255, 255, 255))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


# ── OCR through Ollama ─────────────────────────────────────────────────

def default_ocr_model() -> Optional[str]:
    env = os.environ.get("BEN_PDF_OCR_MODEL")
    if env:
        return env
    from services.ollama_ocr_service import list_vision_models
    local = [m["name"] for m in list_vision_models().get("models", []) if not m.get("cloud")]
    for want in PREFERRED_OCR_MODELS:
        for name in local:
            # "qwen3-vl:2b" matches "qwen3-vl:2b-instruct-bf16"; "qwen3-vl" any tag of it, not "qwen3-vl-ahw"
            if (name.startswith(want) if ":" in want else name.split(":")[0] == want):
                return name
    return local[0] if local else None


def _find_loop(text: str) -> Optional[int]:
    """Where the model starts repeating itself (a short unit 6+ times in a row), or None."""
    m = re.search(r"(.{2,40}?)\1{5,}", text, flags=re.S)
    if not m or len(m.group(1).strip()) == 0:  # runs of spaces or dots are layout, not a loop
        return None
    if re.fullmatch(r"[.\s·…_-]+", m.group(1)):
        return None
    return m.start() + len(m.group(1))  # keep the first occurrence


def _check_ocr(text: str) -> List[str]:
    warnings = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ["empty output"]
    counts: Dict[str, int] = {}
    for l in lines:
        counts[l] = counts.get(l, 0) + 1
    top, k = max(counts.items(), key=lambda kv: kv[1])
    if k >= 4 and len(top) > 3:
        warnings.append(f"line repeated {k} times (model looping?): {top[:60]!r}")
    if re.search(r"(.{8,}?)\1{4,}", text):
        warnings.append("repeated phrase inside a line (model looping?)")
    if "[?]" in text:
        warnings.append(f"{text.count('[?]')} unreadable spots marked [?]")
    return warnings


_gpu_lock = threading.Lock()  # one OCR at a time: there is one GPU

# A dense dictionary page is about 3,000 tokens; a model that loops would otherwise
# write until the request times out (5 min) and the page fails.
MAX_TOKENS = 4096


class OcrError(RuntimeError):
    def __init__(self, message: str, regions: List[Dict[str, Any]]):
        super().__init__(message)
        self.regions = regions


def ocr_page(page: "fitz.Page", model: str, prompt: str, dpi: int, layout: str = "page") -> Dict[str, Any]:
    from common.ocr_prompts import resolve_prompt
    from services.ollama_ocr_service import OllamaOcrService
    prompt_text = resolve_prompt(prompt)
    if model.lower().startswith("deepseek-ocr"):
        # DeepSeek-OCR (and BEn's models trained from it) answers long instructions with
        # nothing; it only knows its own commands (see clients/ollama_client.py)
        from clients.ollama_client import DEEPSEEK_OCR_PROMPT
        prompt_text = DEEPSEEK_OCR_PROMPT
    regions = page_regions(page, layout)
    per_line = layout == "lines"
    if per_line and prompt == "exact_copy" and not model.lower().startswith("deepseek-ocr"):
        prompt_text = resolve_prompt("exact_copy_line")
    max_tokens = 256 if per_line else MAX_TOKENS  # one printed line is ~20-60 tokens
    service = OllamaOcrService(model=model)
    parts, warnings = [], []
    page_imgs: Dict[int, Any] = {}  # dpi -> whole page image, for cutting out lines

    def region_png(reg, at_dpi: int) -> bytes:
        if reg.get("polygon"):
            if at_dpi not in page_imgs:
                from PIL import Image
                pix = page.get_pixmap(dpi=at_dpi, colorspace=fitz.csRGB)
                page_imgs[at_dpi] = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            return _line_image(page_imgs[at_dpi], at_dpi / 72, page.rect.tl, reg["rect"], reg["polygon"])
        return page.get_pixmap(dpi=at_dpi, clip=reg["rect"], colorspace=fitz.csRGB).tobytes("png")

    try:
        if per_line:
            parts, warnings = _ocr_lines(page, regions, model, prompt_text if prompt != "exact_copy" else None,
                                         dpi, service, region_png)
        for i, reg in enumerate(regions if not per_line else [], 1):
            name = f"region {i} ({reg['label']})"
            # A model that loops (typically on figure labels) is often fine at another
            # resolution: one retry at 2/3 of the dpi, then cut the repetition.
            for attempt_dpi in (dpi, max(150, dpi * 2 // 3)):
                png = region_png(reg, attempt_dpi)
                with _gpu_lock:
                    r = service.ocr_from_base64(base64.b64encode(png).decode(), custom_prompt=prompt_text,
                                                model=model, max_tokens=max_tokens)
                text = re.sub(r"^```[a-z]*\n|\n```$", "", (r.get("text") or "").strip())  # some models fence it
                if per_line:  # one region = one printed line, whatever the model did with breaks
                    text = " ".join(l.strip() for l in text.splitlines() if l.strip())
                    text = text.replace("**", "")  # markdown bold: a habit of the AHw-trained models
                looped = r.get("success") and (r.get("done_reason") == "length" or _find_loop(text) is not None)
                if r.get("success") and not looped:
                    if attempt_dpi != dpi:
                        warnings.append(f"{name}: read at {attempt_dpi} dpi after the model looped at {dpi}")
                    break
            if not r.get("success"):
                raise OcrError(f"{name}: {r.get('error') or 'OCR failed'}", regions)
            if looped:
                loop = _find_loop(text)
                if loop is not None:
                    text = text[:loop].rstrip() + " [… model repeated itself; rest of this region cut]"
                warnings.append(f"{name}: model looped (also at {attempt_dpi} dpi); repetition cut, "
                                f"text after it may be missing: check the page image")
            parts.append(unicodedata.normalize("NFC", text))
    finally:
        service.close()
    if per_line:  # lines as printed; a blank line where a new column or full-width line begins
        out = []
        for k, (reg, line) in enumerate(zip(regions, parts)):
            if k and reg["label"] != regions[k - 1]["label"]:
                out.append("")
            out.append(line)
        text = "\n".join(out)
    else:
        text = "\n\n".join(parts)
    return {"text": text, "warnings": warnings + _check_ocr(text), "regions": regions, "parts": parts}


def _stack_lines(pngs: List[bytes]) -> bytes:
    """Line images one below the other, with white space between them."""
    from PIL import Image
    ims = [Image.open(io.BytesIO(p)).convert("RGB") for p in pngs]
    gap = max(8, int(sorted(im.height for im in ims)[len(ims) // 2] * 0.6))
    out = Image.new("RGB", (max(im.width for im in ims) + 2 * gap,
                            sum(im.height for im in ims) + gap * (len(ims) + 1)), (255, 255, 255))
    y = gap
    for im in ims:
        out.paste(im, (gap, y))
        y += im.height + gap
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


_NUMBER_SOUP = re.compile(r"^[\d\s.,:;]*$")


def _invented(line: str) -> bool:
    """A line of nothing but a long string of digits ("5117.034796305707646264075"): what
    a model writes when it does not read the line at all. Printed numbers (page numbers,
    dates, "S. 248") are short or come with words."""
    return bool(_NUMBER_SOUP.match(line)) and sum(c.isdigit() for c in line) >= 10


def _numbered(lines: List[str]) -> List[str]:
    """Drop the "1: ", "2: " ... the model was asked to put in front of its lines, but only
    if it numbered all of them in order (a printed line may itself begin with "2.")."""
    nums = [re.match(rf"^\s*{k}\s*[:.)]\s*", l) for k, l in enumerate(lines, 1)]
    if all(nums):
        return [l[m.end():] for l, m in zip(lines, nums)]
    # "k:" is the form the prompt asks for; when the model numbers only some lines, a "k:"
    # at its own position is still the model's number, not print ("1)" or "1." may be print)
    return [re.sub(rf"^\s*{k}\s*:\s*", "", l, count=1) for k, l in enumerate(lines, 1)]


def _ocr_lines(page: "fitz.Page", regions: List[Dict[str, Any]], model: str, custom_prompt: Optional[str],
               dpi: int, service, region_png) -> Tuple[List[str], List[str]]:
    """Read the detected lines in batches, cheapest first: a whole column (or the header
    row) as one stack of cut-out lines; if the model returns a different number of lines
    or loops, the batch is halved, down to single lines. A single line that still fails is
    marked [?] and reported, for the reviewer to read from the page image.

    Measured on a 1906 two-column page (Qwen3-VL 2B, throttled laptop GPU): a whole
    58-line column in one call came back 58/58, ~1 s per line, against ~10 s per line
    one by one. Models fine-tuned on dictionary entries (the AHw ones) join the stacked
    lines into one paragraph: every batch then falls back to single lines.
    """
    from common.ocr_prompts import resolve_prompt
    deepseek = model.lower().startswith("deepseek-ocr")
    if deepseek:
        from clients.ollama_client import DEEPSEEK_OCR_PROMPT
    parts: List[Optional[str]] = [None] * len(regions)
    warnings: List[str] = []
    stats = {"calls": 0, "splits": 0}

    def ask(png: bytes, prompt: str, max_tokens: int) -> Tuple[str, bool]:
        with _gpu_lock:
            r = service.ocr_from_base64(base64.b64encode(png).decode(), custom_prompt=prompt,
                                        model=model, max_tokens=max_tokens)
        stats["calls"] += 1
        if not r.get("success"):
            raise OcrError(f"line OCR: {r.get('error') or 'OCR failed'}", regions)
        text = re.sub(r"^```[a-z]*\n|\n```$", "", (r.get("text") or "").strip()).replace("**", "")
        bad = r.get("done_reason") == "length" or _find_loop(text) is not None
        return text, bad or any(_invented(l.strip()) for l in text.splitlines() if l.strip())

    def read(lo: int, hi: int) -> None:
        n = hi - lo
        if n == 1:
            prompt = DEEPSEEK_OCR_PROMPT if deepseek else (custom_prompt or resolve_prompt("exact_copy_line"))
            for at_dpi in (dpi, max(150, dpi * 2 // 3)):
                text, looped = ask(region_png(regions[lo], at_dpi), prompt, 256)
                if not looped:
                    parts[lo] = " ".join(l.strip() for l in text.splitlines() if l.strip())
                    return
            parts[lo] = "[?]"
            warnings.append(f"line {lo + 1} ({regions[lo]['label']}): not read, the model looped or wrote "
                            f"invented numbers; "
                            f"read it from the page image")
            return
        prompt = DEEPSEEK_OCR_PROMPT if deepseek else resolve_prompt("exact_copy_lines").replace("{n}", str(n))
        text, looped = ask(_stack_lines([region_png(regions[k], dpi) for k in range(lo, hi)]), prompt, 60 * n + 100)
        lines = _numbered([l.strip() for l in text.splitlines() if l.strip()])
        # the right number of lines can still be a loop: the same line written over and over
        repeats = max((lines.count(l) for l in lines if len(l) > 3), default=0)
        if not looped and len(lines) == n and repeats < 3:
            parts[lo:hi] = lines
            return
        stats["splits"] += 1
        mid = lo + n // 2
        read(lo, mid)
        read(mid, hi)

    # one batch per column / header row: consecutive lines with the same label
    start = 0
    for k in range(1, len(regions) + 1):
        if k == len(regions) or regions[k]["label"] != regions[start]["label"]:
            read(start, k)
            start = k
    if stats["splits"]:
        warnings.append(f"{stats['splits']} batches of lines came back with a different number of lines or "
                        f"looped and were read again in smaller batches ({stats['calls']} calls for {len(regions)} lines)")
    return [unicodedata.normalize("NFC", p or "") for p in parts], warnings


def _region_list(regions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"label": g["label"], "rect": [round(v, 1) for v in g["rect"]]} for g in regions]


# ── A page as BEn stores it: image + lines + line boxes ────────────────

BEN_IMAGE_DPI = 300
BEN_IMAGE_MAX_SIDE = 4000  # px; a scan already at image resolution would otherwise blow up


def ben_page(page: "fitz.Page", route: str, parts: Optional[List[str]] = None,
             regions: Optional[List[Dict[str, Any]]] = None, text: str = "") -> Dict[str, Any]:
    """JPEG of the page and its text as CuReD lines with boxes in image pixels. Embedded
    lines get their real position; OCR lines are spread over their region (column, YOLO
    box), or over the page when the regions are not known."""
    r = page.rect
    dpi = min(BEN_IMAGE_DPI, BEN_IMAGE_MAX_SIDE * 72 / max(r.width, r.height))
    scale = dpi / 72
    pix = page.get_pixmap(dpi=int(dpi), colorspace=fitz.csRGB)
    from PIL import Image
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)

    def box(rect: "fitz.Rect") -> Dict[str, float]:
        return {"x": round((rect.x0 - r.x0) * scale, 1), "y": round((rect.y0 - r.y0) * scale, 1),
                "width": round(rect.width * scale, 1), "height": round(rect.height * scale, 1)}

    lines, boxes = [], []
    if route == "embedded":
        for block in embedded_lines(page)[0]:
            for t, rect in block:
                lines.append(t)
                boxes.append(box(rect))
    else:
        chunks = list(zip(parts, [g["rect"] for g in regions])) if parts and regions and len(parts) == len(regions) \
            else [(text, r)]
        for chunk, rect in chunks:
            ls = [l for l in chunk.splitlines() if l.strip()]
            h = rect.height / max(1, len(ls))
            for i, l in enumerate(ls):
                lines.append(l)
                boxes.append(box(fitz.Rect(rect.x0, rect.y0 + i * h, rect.x1, rect.y0 + (i + 1) * h)))
    return {"image": buf.getvalue(), "lines": lines, "boxes": boxes}


# ── Page ranges, output folder ─────────────────────────────────────────

def parse_pages(spec: Optional[str], count: int) -> List[int]:
    if not spec or spec.strip().lower() == "all":
        return list(range(1, count + 1))
    pages = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b) if b else int(a)
        pages.update(range(max(1, lo), min(count, hi) + 1))
    return sorted(pages)


def _ranges(nums: List[int]) -> str:
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(out)


def default_out_dir(pdf_path: str) -> str:
    from utils.storage_utils import StorageUtils
    base = StorageUtils.BASE_PATH or "data"
    stem = re.sub(r"[^\w.-]+", "_", os.path.splitext(os.path.basename(pdf_path))[0])
    return os.path.abspath(os.path.join(base, "pdf_text", stem))


# ── Plans: settings + sample pages, approved before the batch ──────────

class Plan:
    """Settings for one PDF, tried on sample pages; the batch runs only once approved."""

    def __init__(self, path: str, pages: Optional[str], mode: str, model: Optional[str],
                 dpi: int, layout: str, prompt: str, out_dir: Optional[str]):
        if mode not in ("auto", "embedded", "ocr"):
            raise ValueError("mode must be 'auto', 'embedded' or 'ocr'")
        if not (layout in ("page", "columns", "lines") or layout.startswith("yolo")):
            raise ValueError(f"layout must be {LAYOUTS}")
        self.id = uuid.uuid4().hex[:10]
        self.path = os.path.abspath(path)
        if not os.path.isfile(self.path):
            raise FileNotFoundError(self.path)
        with fitz.open(self.path) as doc:
            self.page_count = doc.page_count
            self.pages = parse_pages(pages, self.page_count)
            self.routes = {n: analyse_page(doc[n - 1]) for n in self.pages}
        self.mode, self.dpi, self.layout, self.prompt = mode, dpi, layout, prompt
        self.model = model
        self.out_dir = out_dir or default_out_dir(self.path)
        self.samples: Dict[int, Dict[str, Any]] = {}  # page -> processed entry incl. text
        self.approved: Optional[Dict[str, Any]] = None

    def route(self, n: int) -> str:
        return self.routes[n]["route"] if self.mode == "auto" else self.mode

    def settings(self) -> Dict[str, Any]:
        return {"mode": self.mode, "layout": self.layout, "ocr_model": self.model, "dpi": self.dpi,
                "prompt": self.prompt, "pages": _ranges(self.pages)}

    def pick_samples(self, wanted: Optional[str] = None) -> List[int]:
        """Hardest page per route: the one with the most diacritics, sub/superscripts and
        warnings (embedded), or a page from the middle of the scan (OCR, skipping covers)."""
        if wanted:
            return [n for n in parse_pages(wanted, self.page_count) if n in self.routes][:3]
        picks = []
        with fitz.open(self.path) as doc:
            emb = [n for n in self.pages if self.route(n) == "embedded"]
            if emb:
                def score(n):
                    text, warns = embedded_text(doc[n - 1])
                    return sum(c in SPECIAL_CHARS for c in text) * 20 + len(text) + 5000 * len(warns)
                body = emb[2:] if len(emb) > 4 else emb  # covers and contents pages are poor samples
                picks.append(max(body, key=score))
            ocr = [n for n in self.pages if self.route(n) == "ocr"]
            if ocr:
                picks.append(ocr[len(ocr) // 2])
        return picks

    def process_page(self, doc: "fitz.Document", n: int) -> Dict[str, Any]:
        """Text of page n with this plan's settings (does not write anything)."""
        t0 = time.time()
        page = doc[n - 1]
        route = self.route(n)
        entry: Dict[str, Any] = {"page": n, "check": self.routes[n]["reason"]}
        try:
            if route in ("embedded", "empty"):
                text, warnings = embedded_text(page)
                entry.update(method="empty" if route == "empty" else "embedded")
            else:
                if not self.model:
                    self.model = default_ocr_model()
                    if not self.model:
                        raise RuntimeError("no local Ollama vision model installed (e.g. ollama pull qwen3-vl:4b)")
                entry.update(method=f"ocr:{self.model}", layout=self.layout, dpi=self.dpi, prompt=self.prompt)
                r = ocr_page(page, self.model, self.prompt, self.dpi, self.layout)
                text, warnings = r["text"], r["warnings"]
                entry["regions"] = _region_list(r["regions"])
                entry["_parts"], entry["_regions"] = r["parts"], r["regions"]  # for BEn's line boxes; not saved
            entry.update(status="done", text=text, chars=len(text), warnings=warnings)
        except Exception as e:
            entry.update(status="failed", error=str(e))
            if isinstance(e, OcrError):
                entry["regions"] = _region_list(e.regions)
        entry["seconds"] = round(time.time() - t0, 1)
        return entry

    def run_samples(self, wanted: Optional[str] = None) -> List[Dict[str, Any]]:
        out = []
        with fitz.open(self.path) as doc:
            for n in self.pick_samples(wanted):
                self.samples[n] = self.process_page(doc, n)
                out.append(self.samples[n])
        return out


_plans: Dict[str, Plan] = {}


def make_plan(**kwargs) -> Plan:
    plan = Plan(**kwargs)
    _plans[plan.id] = plan
    return plan


def get_plan(plan_id: str) -> Optional[Plan]:
    return _plans.get(plan_id)


# ── Jobs: the approved batch ───────────────────────────────────────────

class PdfTextJob:
    def __init__(self, plan: Plan, overwrite: bool = False, ben_parent: Optional[str] = "PDF extractions"):
        if not plan.approved:
            raise PermissionError("plan not approved: check its sample pages first")
        self.id = uuid.uuid4().hex[:10]
        self.plan = plan
        self.path, self.pages, self.out_dir = plan.path, plan.pages, plan.out_dir
        self.overwrite = overwrite
        # Results are kept in BEn (CuReD dataset <ben_parent>/<pdf name>); None = files only
        self.ben_parent = ben_parent
        self.ben_name = os.path.splitext(os.path.basename(self.path))[0]
        self.ben_dataset_id: Optional[int] = None
        self.ben_error: Optional[str] = None
        self.status = "pending"
        self.error: Optional[str] = None
        self.current: Optional[int] = None
        self.cancelled = False
        self.started = time.time()
        os.makedirs(self.out_dir, exist_ok=True)
        self.manifest = self._load_manifest()
        self.manifest.setdefault("approvals", []).append(
            {**plan.approved, "plan_id": plan.id, "settings": plan.settings(), "sample_pages": sorted(plan.samples)})

    # manifest.json: {"pdf", "pages": {"7": {...}}, "approvals": [...]}; kept across runs for resuming
    def _manifest_path(self) -> str:
        return os.path.join(self.out_dir, "manifest.json")

    def _load_manifest(self) -> Dict[str, Any]:
        try:
            with open(self._manifest_path(), encoding="utf-8") as f:
                m = json.load(f)
            if m.get("pdf") == self.path:
                return m
        except Exception:
            pass
        return {"pdf": self.path, "page_count": self.plan.page_count, "pages": {}}

    def _save_manifest(self) -> None:
        tmp = self._manifest_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._manifest_path())

    def page_file(self, n: int) -> str:
        return os.path.join(self.out_dir, f"page_{n:04d}.txt")

    def start(self) -> "PdfTextJob":
        threading.Thread(target=self._run, name=f"pdf-text-{self.id}", daemon=True).start()
        return self

    def _same_settings(self, entry: Dict[str, Any], n: int) -> bool:
        route = self.plan.route(n)
        if route in ("embedded", "empty"):
            return entry.get("method") in ("embedded", "empty")
        return (entry.get("method") == f"ocr:{self.plan.model}" and entry.get("layout") == self.plan.layout
                and entry.get("prompt") == self.plan.prompt)

    # ── BEn ────────────────────────────────────────────────────────────

    def _ben_open(self) -> None:
        """Connect to BEn (starting it headless if needed) and find or make the dataset."""
        from services.ben_store import BenStore
        self.ben = BenStore()
        self.ben.ensure_running()
        self.ben_dataset_id = self.ben.dataset_for(self.ben_name, self.ben_parent)
        self.ben_existing = {BenStore.publication(t): t for t in self.ben.texts(self.ben_dataset_id)}
        self.manifest["ben"] = {"dataset_id": self.ben_dataset_id, "dataset": f"{self.ben_parent}/{self.ben_name}"}

    def _ben_store(self, doc: "fitz.Document", n: int, entry: Dict[str, Any], text: str,
                   parts=None, regions=None) -> None:
        pub = f"{self.ben_name}/p{n:04d}"
        route = "embedded" if entry.get("method") in ("embedded", "empty") else "ocr"
        try:
            page = ben_page(doc[n - 1], route, parts, regions, text)
            labels = ["pdf-embedded"] if route == "embedded" else ["pdf-ocr", "draft"]
            if entry.get("warnings"):
                labels.append("warnings")
            approval = (self.manifest.get("approvals") or [{}])[-1]
            meta = {"source": "ben-pdf", "pdf": self.path, "page": n, "method": entry.get("method"),
                    "warnings": entry.get("warnings", []), "approval_notes": approval.get("notes", ""),
                    "plan_id": approval.get("plan_id")}
            r = self.ben.save_page(self.ben_dataset_id, pub, page["image"], page["lines"], page["boxes"],
                                   labels, meta, existing=self.ben_existing.get(pub))
            entry["ben"] = {"publication": pub, **r}
        except Exception as e:
            entry["ben"] = {"publication": pub, "error": str(e)}

    # ── run ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        self.status = "running"
        try:
            if self.ben_parent:
                try:
                    self._ben_open()
                except Exception as e:
                    self.ben_error = f"results not stored in BEn: {e}"
                    self.ben_parent = None
            with fitz.open(self.path) as doc:
                for n in self.pages:
                    if self.cancelled:
                        self.status = "cancelled"
                        break
                    self.current = n
                    old = self.manifest["pages"].get(str(n))
                    if (not self.overwrite and old and old.get("status") == "done"
                            and os.path.exists(self.page_file(n)) and self._same_settings(old, n)):
                        # done in an earlier run with the same settings: only store it in BEn if missing
                        if self.ben_parent and not (old.get("ben") or {}).get("text_id"):
                            with open(self.page_file(n), encoding="utf-8") as f:
                                self._ben_store(doc, n, old, f.read().rstrip())
                            self._save_manifest()
                        continue
                    edited = self._edited_in_ben(n) if self.ben_parent else None
                    if edited:
                        # someone worked on this page in BEn: never read it again over their work
                        pub = f"{self.ben_name}/p{n:04d}"
                        entry = dict(old) if old else {"page": n, "status": "skipped"}
                        entry["ben"] = {**(entry.get("ben") or {"publication": pub}), "skipped": edited}
                        self.manifest["pages"][str(n)] = entry
                        self._save_manifest()
                        continue
                    entry = self.plan.samples.get(n) or self.plan.process_page(doc, n)  # samples are reused
                    entry = dict(entry)
                    text = entry.pop("text", None)
                    parts, regions = entry.pop("_parts", None), entry.pop("_regions", None)
                    if entry.get("status") == "done":
                        with open(self.page_file(n), "w", encoding="utf-8") as f:
                            f.write(text + "\n")
                        if self.ben_parent:
                            self._ben_store(doc, n, entry, text, parts, regions)
                    elif old and old.get("status") == "done" and os.path.exists(self.page_file(n)):
                        # a failed rerun keeps the earlier result rather than losing it
                        entry = {**old, "last_rerun_error": entry.get("error")}
                    self.manifest["pages"][str(n)] = entry
                    self._save_manifest()
            self._write_document()
            if self.status == "running":
                failed = [p for p, e in self.manifest["pages"].items() if e.get("status") == "failed" and int(p) in self.pages]
                self.status = "completed_with_errors" if failed else "completed"
        except Exception as e:
            logger.exception("PDF text job failed")
            self.status, self.error = "failed", str(e)
        finally:
            self.current = None
            self.manifest["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save_manifest()

    def _edited_in_ben(self, n: int) -> Optional[str]:
        """Why page n must not be replaced in BEn, or None. CuReD's curated/reviewed flags
        are not enough: an AI or a person may correct the lines without setting them (on
        2026-11-21 a rerun replaced a proofread article this way). So the page in BEn is
        compared with what ben-pdf stored there; any difference is someone's work."""
        from services.ben_store import BenStore
        item = self.ben_existing.get(f"{self.ben_name}/p{n:04d}")
        if not item:
            return None
        if BenStore.corrected(item) or "proofread" in (item.get("labels") or []):
            return "corrected or proofread in BEn; left unchanged"
        if not os.path.exists(self.page_file(n)):
            return "in BEn but not from this extraction; left unchanged"
        with open(self.page_file(n), encoding="utf-8") as f:
            stored = [l for l in f.read().splitlines() if l.strip()]
        try:
            now = self.ben.latest_lines(item["text_id"])
        except Exception:
            return "could not read the page from BEn to check for corrections; left unchanged"
        if now is not None and [l for l in now if l.strip()] != stored:
            return "edited in BEn since ben-pdf stored it; left unchanged"
        return None

    def _write_document(self) -> None:
        """All finished pages in order, each under a header naming its source."""
        parts = []
        for n in range(1, self.plan.page_count + 1):
            e = self.manifest["pages"].get(str(n))
            if not e or e.get("status") != "done" or not os.path.exists(self.page_file(n)):
                continue
            with open(self.page_file(n), encoding="utf-8") as f:
                parts.append(f"=== page {n} ({e['method']}) ===\n{f.read().rstrip()}\n")
        with open(os.path.join(self.out_dir, "document.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(parts))

    def summary(self) -> Dict[str, Any]:
        mine = {p: e for p, e in self.manifest["pages"].items() if int(p) in self.pages}
        methods: Dict[str, List[int]] = {}
        for p, e in mine.items():
            methods.setdefault(e.get("method") or e.get("status"), []).append(int(p))
        return {
            "job_id": self.id,
            "status": self.status,
            "error": self.error,
            "pdf": self.path,
            "out_dir": self.out_dir,
            "document": os.path.join(self.out_dir, "document.txt"),
            "pages_requested": _ranges(self.pages),
            "pages_done": sum(1 for e in mine.values() if e.get("status") == "done"),
            "pages_total": len(self.pages),
            "current_page": self.current,
            "by_method": {k: _ranges(sorted(v)) for k, v in methods.items()},
            "failed": {p: e["error"] for p, e in mine.items() if e.get("status") == "failed"},
            "warnings": {p: e["warnings"] for p, e in mine.items() if e.get("warnings")},
            "settings": self.plan.settings(),
            "ben": {
                "dataset": f"{self.ben_parent}/{self.ben_name}" if self.ben_parent else None,
                "dataset_id": self.ben_dataset_id,
                "pages_stored": sum(1 for e in mine.values() if (e.get("ben") or {}).get("transliteration_id")),
                "left_unchanged_corrected": _ranges(sorted(int(p) for p, e in mine.items() if (e.get("ben") or {}).get("skipped"))),
                "errors": {p: e["ben"]["error"] for p, e in mine.items() if (e.get("ben") or {}).get("error")},
                "error": self.ben_error,
            },
            "elapsed_seconds": round(time.time() - self.started, 1),
        }


_jobs: Dict[str, PdfTextJob] = {}


def start_job(plan: Plan, overwrite: bool = False, ben_parent: Optional[str] = "PDF extractions") -> PdfTextJob:
    job = PdfTextJob(plan, overwrite, ben_parent)
    _jobs[job.id] = job
    return job.start()


def get_job(job_id: str) -> Optional[PdfTextJob]:
    return _jobs.get(job_id)
