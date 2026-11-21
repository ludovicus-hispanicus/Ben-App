"""Tests for services/pdf_text_service.py that need no GPU, no Ollama and no BEn server:
page routing, embedded-text cleanup and the batch ladder of the 'lines' layout (driven
by a fake OCR service that merges, loops or repeats lines on purpose).

Run from server/:  py -m pytest tests
"""
import base64
import os
import sys
import unicodedata

import fitz
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services import pdf_text_service as pts  # noqa: E402


def nfc(s):
    return unicodedata.normalize("NFC", s)


# ── Page ranges ──────────────────────────────────────────────────────────

def test_parse_pages_and_ranges_round_trip():
    assert pts.parse_pages("1-3, 5,9-8", 10) == [1, 2, 3, 5]
    assert pts.parse_pages("all", 3) == [1, 2, 3]
    assert pts.parse_pages("8-20", 10) == [8, 9, 10]
    assert pts._ranges([1, 2, 3, 5, 7, 8]) == "1-3,5,7-8"
    assert pts._ranges([]) == ""


# ── Routing: embedded / ocr / empty ──────────────────────────────────────

def _png(w=400, h=600, gray=200):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), False)
    pix.set_rect(pix.irect, (gray, gray, gray))
    return pix.tobytes("png")


PROSE = ("The stylus was cut from a reed and its tip shaped to leave the wedge. "
         "Scribes held it between thumb and fingers and pressed it into the clay at an angle. ") * 3


@pytest.fixture
def mixed_pdf(tmp_path):
    doc = fitz.open()
    p = doc.new_page()                      # 1: born-digital
    p.insert_textbox(fitz.Rect(50, 50, 550, 700), PROSE, fontsize=11)
    p = doc.new_page()                      # 2: scan, no text layer
    p.insert_image(p.rect, stream=_png())
    p = doc.new_page()                      # 3: scan with an invisible OCR layer
    p.insert_image(p.rect, stream=_png())
    p.insert_textbox(fitz.Rect(50, 50, 550, 700), PROSE, fontsize=11, render_mode=3)
    doc.new_page()                          # 4: blank
    p = doc.new_page()                      # 5: scan, no text layer (same reason as 2)
    p.insert_image(p.rect, stream=_png())
    path = str(tmp_path / "mixed.pdf")
    doc.save(path)
    return path


def test_routes(mixed_pdf):
    with fitz.open(mixed_pdf) as doc:
        routes = [pts.analyse_page(p)["route"] for p in doc]
    assert routes == ["embedded", "ocr", "ocr", "empty", "ocr"]


def test_inspect_groups_reasons_into_page_ranges(mixed_pdf):
    r = pts.inspect_pdf(mixed_pdf)
    assert r["routes"] == {"embedded": "1", "ocr": "2-3,5", "empty": "4"}
    by_reason = {e["reason"]: e["pages"] for e in r["not_embedded"]}
    assert by_reason["no text layer; the page is an image (scan)"] == "2,5"
    assert by_reason["text layer is invisible OCR text laid over a scan"] == "3"
    assert by_reason["blank page"] == "4"


# ── Embedded text cleanup (synthetic rawdict lines) ─────────────────────

def _span(text, x, font="Times", size=10.0, y=100.0, flags=0, char_boxes=None):
    """A rawdict span: one entry per character, 5 pt wide, baseline at y."""
    chars = []
    for i, c in enumerate(text):
        x0 = x + 5 * i
        bbox = char_boxes[i] if char_boxes else (x0, y - size * 0.8, x0 + 5, y + size * 0.2)
        chars.append({"c": c, "bbox": bbox, "origin": (x0, y)})
    return {"chars": chars, "font": font, "size": size, "flags": flags, "origin": (x, y)}


def _line(*spans):
    return {"spans": list(spans)}


def test_superscript_footnote_number():
    undecoded = {}
    text = pts._line_text(_line(_span("stylus", 0), _span("12", 30, size=6, y=96)), undecoded)
    assert text == "stylus¹²"


def test_subscript_sign_number():
    text = pts._line_text(_line(_span("i-du", 0), _span("11", 20, size=6, y=102.5)), {})
    assert text == "i-du₁₁"


def test_superscript_without_unicode_form_is_marked():
    text = pts._line_text(_line(_span("x", 0, size=6, y=96), _span("abc main", 10)), {})
    assert text == "ˣabc main"
    text = pts._line_text(_line(_span("giš", 0, size=6, y=96), _span("tukul main", 20)), {})
    assert text == "^{giš}tukul main"


def test_small_caps_font_is_uppercased_with_glued_letter_from_other_font():
    # GIŠ.ḪUR printed as small caps "giš." + a small lowercase "ḫ" from Times + small caps "ur"
    line = _line(_span("see ", 0, size=10), _span("giš.", 20, font="Andron-SC700", size=10),
                 _span("ḫ", 40, font="Times", size=7.5), _span("ur", 45, font="Andron-SC700", size=10))
    assert pts._line_text(line, {}) == "see GIŠ.ḪUR"


def test_tex_breve_below_becomes_h_with_breve_below():
    # dvips: "H" then a spacing breve glyph drawn under it
    h = (0, 90, 7, 100)
    breve = (1, 101, 6, 104)  # below the letter's middle
    line = _line(_span("H˘a", 0, char_boxes=[h, breve, (8, 92, 13, 100)]))
    assert nfc(pts._line_text(line, {})) == nfc("Ḫa")


def test_tex_caron_above_becomes_s_caron():
    s = (0, 93, 5, 100)
    caron = (0.5, 88, 4.5, 92)
    line = _line(_span("ˇsa", 0, char_boxes=[caron, s, (6, 93, 11, 100)]))
    assert nfc(pts._line_text(line, {})) == "ša"


def test_orphan_accent_and_unmapped_glyph_marked_not_guessed():
    undecoded = {}
    line = _line(_span("5 ˙ 2 mm " + chr(0xFFFD) + " wide", 0, font="CMSY10"))
    text = pts._line_text(line, undecoded)
    assert text == "5 [?] 2 mm [?] wide"
    assert undecoded == {"CMSY10": 2}


def test_line_of_unmapped_glyphs_is_dropped():
    assert pts._line_text(_line(_span(chr(0xE001) * 8, 0)), {}) == ""


TIMES = r"C:\Windows\Fonts\times.ttf"  # the base-14 fonts have neither ligatures nor š


@pytest.mark.skipif(not os.path.exists(TIMES), reason="needs Times New Roman")
def test_embedded_lines_on_a_real_pdf_page():
    doc = fitz.open()
    p = doc.new_page()
    p.insert_font(fontname="tnr", fontfile=TIMES)
    p.insert_text((72, 100), "ﬁne stylus, ša Grösse", fontname="tnr", fontsize=11)
    p.insert_text((72, 120), "Ta" + chr(0xAD), fontname="tnr", fontsize=11)
    blocks, warnings = pts.embedded_lines(p)
    assert [t for b in blocks for t, _ in b] == ["fine stylus, ša Grösse", "Ta-"]
    assert warnings == []


# ── Loop detection and numbering ─────────────────────────────────────────

def test_find_loop():
    assert pts._find_loop("a-na šar-ri " + "be-li-ia " * 8) is not None
    assert pts._find_loop("Contents " + "." * 40 + " 12") is None
    assert pts._find_loop("an ordinary line of text") is None


def test_numbered_strips_only_complete_numbering():
    assert pts._numbered(["1: foo", "2. bar", "3) baz"]) == ["foo", "bar", "baz"]
    # a printed line that happens to begin with a number is left alone
    assert pts._numbered(["2. Tafel", "nicht nummeriert"]) == ["2. Tafel", "nicht nummeriert"]


def test_check_ocr_warnings():
    assert pts._check_ocr("") == ["empty output"]
    w = pts._check_ocr("\n".join(["same line here"] * 5))
    assert any("repeated 5 times" in x for x in w)
    assert any("1 unreadable" in x for x in pts._check_ocr("a [?] b"))


# ── The 'lines' batch ladder, with a fake OCR model ──────────────────────
# region_png returns b"L<k>" for line k; _stack_lines joins them with "|", so the fake
# model sees which lines a request holds and answers with the true text "text <k>",
# unless a scenario tells it to misbehave.

TRUTH = "text {}"


class FakeOcr:
    def __init__(self, behave=None):
        self.behave = behave or (lambda ks, attempt: None)
        self.calls = []

    def ocr_from_base64(self, b64, custom_prompt=None, model=None, max_tokens=None):
        ks = [int(p[1:]) for p in base64.b64decode(b64).decode().split("|")]
        attempt = sum(1 for c in self.calls if c == ks)
        self.calls.append(ks)
        special = self.behave(ks, attempt)
        if special is not None:
            return special
        if len(ks) == 1:
            return {"success": True, "text": TRUTH.format(ks[0]), "done_reason": "stop"}
        text = "\n".join(f"{i}: {TRUTH.format(k)}" for i, k in enumerate(ks, 1))
        return {"success": True, "text": text, "done_reason": "stop"}


@pytest.fixture
def ladder(monkeypatch):
    monkeypatch.setattr(pts, "_stack_lines", lambda pngs: b"|".join(pngs))

    def run(labels, behave=None, model="qwen3-vl:2b-instruct-bf16"):
        regions = [{"label": lab, "rect": fitz.Rect(0, 10 * k, 100, 10 * k + 8)} for k, lab in enumerate(labels)]
        fake = FakeOcr(behave)
        parts, warnings = pts._ocr_lines(None, regions, model, None, 300, fake,
                                         lambda reg, dpi: f"L{regions.index(reg)}".encode())
        return parts, warnings, fake.calls
    return run


def ok(text):
    return {"success": True, "text": text, "done_reason": "stop"}


def test_whole_column_in_one_call(ladder):
    parts, warnings, calls = ladder(["line (left)"] * 6)
    assert parts == [TRUTH.format(k) for k in range(6)]
    assert calls == [[0, 1, 2, 3, 4, 5]]
    assert warnings == []


def test_one_batch_per_column(ladder):
    parts, warnings, calls = ladder(["line (full width)"] + ["line (left)"] * 3 + ["line (right)"] * 2)
    assert calls == [[0], [1, 2, 3], [4, 5]]
    assert parts == [TRUTH.format(k) for k in range(6)]


def test_merged_lines_fall_back_to_smaller_batches(ladder):
    # the model joins any batch of more than 2 lines into one paragraph
    def merge(ks, attempt):
        if len(ks) > 2:
            return ok(" ".join(TRUTH.format(k) for k in ks))
    parts, warnings, calls = ladder(["line (left)"] * 8, merge)
    assert parts == [TRUTH.format(k) for k in range(8)]
    assert calls[0] == list(range(8))
    assert len(calls) == 7  # 8 -> 4+4 -> 2+2+2+2
    assert any("smaller batches" in w for w in warnings)


def test_right_count_but_repeated_line_is_a_loop(ladder):
    def repeat(ks, attempt):
        if len(ks) == 6:
            return ok("\n".join(f"{i}: the same line" for i in range(1, 7)))
    parts, warnings, calls = ladder(["line (left)"] * 6, repeat)
    assert parts == [TRUTH.format(k) for k in range(6)]
    assert calls[1:] == [[0, 1, 2], [3, 4, 5]]


def test_hit_token_limit_counts_as_loop(ladder):
    def cut(ks, attempt):
        if len(ks) == 4:
            return {"success": True, "text": "\n".join(TRUTH.format(k) for k in ks), "done_reason": "length"}
    parts, _, calls = ladder(["line (left)"] * 4, cut)
    assert parts == [TRUTH.format(k) for k in range(4)]
    assert calls[1:] == [[0, 1], [2, 3]]


def test_single_line_that_keeps_looping_is_marked_for_the_reviewer(ladder):
    def bad_line_2(ks, attempt):
        if 2 in ks:
            return ok("ka-ka-ka-ka-ka-ka-ka-ka-ka-ka-ka-ka")
    parts, warnings, calls = ladder(["line (left)"] * 4, bad_line_2)
    assert parts == ["text 0", "text 1", "[?]", "text 3"]
    assert calls.count([2]) == 2  # normal dpi, then 2/3 dpi
    assert any(w.startswith("line 3 (line (left))") and "page image" in w for w in warnings)


def test_single_line_read_again_at_lower_dpi(ladder):
    def first_try_loops(ks, attempt):
        if ks == [1] and attempt == 0:
            return {"success": True, "text": "x", "done_reason": "length"}
        if len(ks) > 1:
            return ok("merged")
    parts, warnings, _ = ladder(["line (left)"] * 2, first_try_loops)
    assert parts == ["text 0", "text 1"]
    assert not any("[?]" in p for p in parts)


def test_ocr_failure_raises(ladder):
    with pytest.raises(pts.OcrError):
        ladder(["line (left)"] * 3, lambda ks, attempt: {"success": False, "error": "timeout"})
