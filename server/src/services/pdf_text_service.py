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
LAYOUTS = "'page' (whole page), 'columns' (split at the gutter) or 'yolo:<model>' (BEn YOLO regions)"

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


def embedded_text(page: "fitz.Page") -> Tuple[str, List[str]]:
    """The page's text layer, cleaned; and warnings (glyphs that could not be decoded)."""
    flags = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP  # no PRESERVE_LIGATURES
    blocks = page.get_text("rawdict", flags=flags)["blocks"]
    undecoded: Dict[str, int] = {}
    paras = []
    for b in blocks:
        if b.get("type") != 0:
            continue
        lines = [_line_text(l, undecoded).rstrip() for l in b["lines"]]
        lines = [l for l in lines if l.strip()]
        if lines:
            paras.append("\n".join(lines))
    text = "\n\n".join(paras)
    for lig, plain in _LIGATURES.items():
        text = text.replace(lig, plain)
    # soft hyphen: printed as "-" where the line breaks, invisible elsewhere
    text = re.sub(_SOFT_HYPHEN + r"[ \t]*\n", "-\n", text).replace(_SOFT_HYPHEN, "")
    warnings = []
    if undecoded:
        fonts = ", ".join(f"{f} ({n})" for f, n in sorted(undecoded.items(), key=lambda kv: -kv[1]))
        warnings.append(f"{sum(undecoded.values())} glyphs without Unicode mapping marked [?] "
                        f"(fonts: {fonts}); likely math symbols or Greek; check the page image")
    return unicodedata.normalize("NFC", text), warnings


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
    for p in pages:
        by_route.setdefault(p["route"], []).append(p["page"])
    return {
        "path": os.path.abspath(path),
        "page_count": len(pages),
        "metadata": meta,
        "routes": {k: _ranges(v) for k, v in by_route.items()},
        "not_embedded": [{k: p[k] for k in ("page", "route", "reason")} for p in pages if p["route"] != "embedded"],
    }


# ── Layout: which parts of a page go to OCR, in which order ────────────

def _column_gutter(pix: "fitz.Pixmap") -> int:
    """x (pixels) of the emptiest vertical strip in the middle third of the page: the gutter."""
    import numpy as np
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].mean(axis=2)
    dark = gray < 128
    # scanner borders: rows or columns dark over most of their length
    dark[dark.mean(axis=1) > 0.5, :] = False
    dark[:, dark.mean(axis=0) > 0.5] = False
    lo, hi = int(pix.width * 0.35), int(pix.width * 0.65)
    ink = dark[:, lo:hi].sum(axis=0).astype(float)
    ink = np.convolve(ink, np.ones(9) / 9, mode="same")  # ignore single-pixel gaps between letters
    return lo + int(ink.argmin())


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


def page_regions(page: "fitz.Page", layout: str) -> List[Dict[str, Any]]:
    """The parts of the page sent to OCR one by one, in reading order."""
    r = page.rect
    if layout in ("page", "", None):
        return [{"rect": fitz.Rect(r), "label": "page"}]
    if layout == "columns":
        pix = page.get_pixmap(dpi=100, colorspace=fitz.csRGB)
        x = r.x0 + _column_gutter(pix) / pix.width * r.width
        return [{"rect": fitz.Rect(r.x0, r.y0, x, r.y1), "label": "left column"},
                {"rect": fitz.Rect(x, r.y0, r.x1, r.y1), "label": "right column"}]
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
    regions = page_regions(page, layout)
    service = OllamaOcrService(model=model)
    parts, warnings = [], []
    try:
        for i, reg in enumerate(regions, 1):
            name = f"region {i} ({reg['label']})"
            # A model that loops (typically on figure labels) is often fine at another
            # resolution: one retry at 2/3 of the dpi, then cut the repetition.
            for attempt_dpi in (dpi, max(150, dpi * 2 // 3)):
                png = page.get_pixmap(dpi=attempt_dpi, clip=reg["rect"], colorspace=fitz.csRGB).tobytes("png")
                with _gpu_lock:
                    r = service.ocr_from_base64(base64.b64encode(png).decode(), custom_prompt=prompt_text,
                                                model=model, max_tokens=MAX_TOKENS)
                text = re.sub(r"^```[a-z]*\n|\n```$", "", (r.get("text") or "").strip())  # some models fence it
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
            parts.append(text)
    finally:
        service.close()
    text = unicodedata.normalize("NFC", "\n\n".join(parts))
    return {"text": text, "warnings": warnings + _check_ocr(text), "regions": regions}


def _region_list(regions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"label": g["label"], "rect": [round(v, 1) for v in g["rect"]]} for g in regions]


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
        if not (layout in ("page", "columns") or layout.startswith("yolo")):
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
    def __init__(self, plan: Plan, overwrite: bool = False):
        if not plan.approved:
            raise PermissionError("plan not approved: check its sample pages first")
        self.id = uuid.uuid4().hex[:10]
        self.plan = plan
        self.path, self.pages, self.out_dir = plan.path, plan.pages, plan.out_dir
        self.overwrite = overwrite
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

    def _run(self) -> None:
        self.status = "running"
        try:
            with fitz.open(self.path) as doc:
                for n in self.pages:
                    if self.cancelled:
                        self.status = "cancelled"
                        break
                    self.current = n
                    old = self.manifest["pages"].get(str(n))
                    if (not self.overwrite and old and old.get("status") == "done"
                            and os.path.exists(self.page_file(n)) and self._same_settings(old, n)):
                        continue  # done in an earlier run with the same settings
                    entry = self.plan.samples.get(n) or self.plan.process_page(doc, n)  # samples are reused
                    entry = dict(entry)
                    text = entry.pop("text", None)
                    if entry.get("status") == "done":
                        with open(self.page_file(n), "w", encoding="utf-8") as f:
                            f.write(text + "\n")
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
            "elapsed_seconds": round(time.time() - self.started, 1),
        }


_jobs: Dict[str, PdfTextJob] = {}


def start_job(plan: Plan, overwrite: bool = False) -> PdfTextJob:
    job = PdfTextJob(plan, overwrite)
    _jobs[job.id] = job
    return job.start()


def get_job(job_id: str) -> Optional[PdfTextJob]:
    return _jobs.get(job_id)
