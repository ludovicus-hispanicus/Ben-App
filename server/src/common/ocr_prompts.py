"""
Centralized OCR prompt registry.

All OCR clients (OpenAI, Gemini, Anthropic, vLLM, Ollama, etc.) import
prompts from here so that edits made via the API are visible everywhere.
"""

import logging
import re
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


def _load_tei_lex0_prompt() -> str:
    """Load TEI Lex-0 prompt from the prompt builder (with gold examples)."""
    try:
        from services.tei_prompt_builder import tei_prompt_builder
        return tei_prompt_builder.build_system_prompt()
    except Exception as e:
        logger.warning(f"Could not load TEI Lex-0 system prompt: {e}")
        return "Transcribe this dictionary page into TEI Lex-0 XML. Return only raw <entry> elements."


PROMPTS: dict[str, str] = {
    "plain": "OCR this image. Output the text exactly as shown, line by line. Do not include any introduction or explanation.",
    "markdown": "OCR this image and output as markdown format. Preserve structure with headers, bold, italic as appropriate.",
    "dictionary": """You are an expert Assyriologist specializing in Akkadian lexicography.
Perform high-precision OCR on the attached image containing a main dictionary entry from the AHw (Akkadisches Handwoerterbuch).

Language: Akkadian (transliterated). Content: Full dictionary entries with headwords, translations, references, and examples.

STRICT EXTRACTION RULES:
1. Preserve diacritics: distinguish macrons (ā, ē, ī, ū), circumflexes (â, ê, î, û), the glottal stop (ʾ), and the ayin (ʿ).
2. Special consonants: preserve ḫ, š, ś, ṣ, ṭ, g̃ exactly — do not substitute with h, s, t, or g. The character g̃ (g with tilde) is a valid Akkadian consonant — never replace or alter it.
3. Parentheticals: maintain all parentheses exactly, e.g., (w)aʾāru(m).
4. Abbreviations and reference signs: preserve exactly as written.
5. No normalization: do not correct the spelling. Prioritize visual evidence over linguistic probability.
6. UNKNOWN SYMBOLS: If you encounter a small symbol, mark, or special character that you cannot confidently identify or map to a known Unicode character, output ↑ (U+2191) in its place. Do NOT guess or substitute with a visually similar but incorrect character.

MARKDOWN FORMATTING — preserve the visual style of the original:
- **bold** → headwords and lemmas that appear larger, darker, or in bold typeface. Lemmas can be enclosed in parentheses or brackets, e.g., **(*)abālu**, **[a]bātu**, **(parāsu)**, **[lemma]**, **(pa-ra-su)**.
- *italic* → Akkadian words in transliteration and lemmas that appear in italic typeface (not bold). Italic lemmas can also be in parentheses or brackets, e.g., *(parāsu)*, *[lemma]*, *(pa-ra-su)*.
- Superscript: use <sup>text</sup> for superscript characters (e.g., determinatives, note markers)
- Subscript: use <sub>text</sub> for subscript characters (e.g., index numbers like ₁ ₂ ₃)
- UPPERCASE → Sumerian logograms (e.g., DINGIR, LÚ) — keep as uppercase, no extra markup
- Keep line breaks as in the original layout

Output ONLY the formatted markdown text. No explanations, no code fences.""",
    "cad": """You are an expert Assyriologist specializing in Akkadian lexicography.
Perform high-precision OCR on the attached image containing a main dictionary entry from the CAD (Chicago Assyrian Dictionary).

OUTPUT STRUCTURE — every paragraph is wrapped in a tag. There is NO untagged paragraph text. Every block of body text MUST be inside one of these tags:

  <entry>...</entry>             — wraps a whole dictionary entry. Usually begins at a bold headword, but a page may start MID-ENTRY (the headword was on the previous page). In that case, still open <entry> at the top of the visible content; the <entry> just won't begin with a headword.
  <section>...</section>         — each BODY-FONT paragraph (header line; sense markers like <b>1.</b>, <b>a)</b>, <b>1′</b>; citation paragraphs; cross-references like "See also …").
  <lex>...</lex>                 — each SMALLER-FONT lexical/bilingual paragraph. Identified by font size ALONE (visibly smaller than body). Position does NOT matter — a page may START with one or more <lex> paragraphs if the entry's headword is on the previous page.
  <bibliography>...</bibliography> — each SMALLER-FONT end-of-entry secondary-literature paragraph. Identified by font size AND "Author, Work Year Page" format. A page may start with <bibliography> if a long previous entry's bibliography continues here.
  <col>A</col> / <col>B</col>    — column-break markers, placed wherever the column changes (between entries, between sections, or even mid-section when a paragraph crosses columns).

Rules for splitting:
  - A new <entry> starts at every new bold headword. If the visible page begins mid-entry (no headword at top), open <entry> at the top of visible content anyway.
  - A new <section> / <lex> / <bibliography> starts at every visual paragraph break: a new bold marker (<b>1.</b>, <b>a)</b>, <b>2′</b>), a parenthesized label like "(a):" / "(b)—", an indented line, or a font-size change.
  - FONT SIZE IS THE ONLY criterion for choosing <lex> vs <section>. Smaller-font paragraph → <lex> (or <bibliography>, see below). Body-font paragraph → <section>. Never use position (e.g. "first on page", "after header") instead of font size.
  - Whitespace and newlines in your output are IGNORED by downstream processing — only the tags define structure. You may output everything on one line or break it for readability; the tag boundaries are what matter.

Example output:

<col>A</col>
<entry><section><b>meḫû A</b> s.; storm; from OAkk on; cf. <i>maḫû</i>.</section><section><b>a)</b> in gen.: <i>citation</i> ref; <i>citation</i> ref.</section><section><b>b)</b> in lit.: <i>citation</i> ref.</section><lex>giš.IM = <i>meḫû</i> Hh. ...</lex></entry>
<entry><section><b>meḫû B</b> (<i>meḫiu</i>) s.; evening; OAkk. (Elam); cf. <i>tamḫû</i>.</section><section><i>citation</i> ref.</section></entry>
<col>B</col>
<entry><section><b>mēkeku</b> s.; scratcher, scraper; lex.*; cf. <i>ekēku</i>.</section><lex>giš.úr.gaz = <i>me-ke-ku</i>, ... Hh. VII A 36ff.</lex></entry>

Language: Akkadian (transliterated). Content: Full dictionary entries with headwords, translations, references, and examples.

STRICT EXTRACTION RULES:
1. Preserve diacritics: distinguish macrons (ā, ē, ī, ū), circumflexes (â, ê, î, û), the glottal stop (ʾ), and the ayin (ʿ).
2. Special consonants: preserve ḫ, š, ś, ṣ, ṭ, g̃ exactly — do not substitute with h, s, t, or g. The character g̃ (g with tilde) is a valid Akkadian consonant — never replace or alter it.
3. Parentheticals: maintain all parentheses exactly, e.g., (w)aʾāru(m).
4. Abbreviations and reference signs: preserve exactly as written.
5. No normalization: do not correct the spelling. Prioritize visual evidence over linguistic probability.
6. EXCLUSIONS: Do NOT include guide-words (the words at the very top of the page) or page numbers. Focus exclusively on the dictionary body.

INLINE FORMATTING (HTML tags only — do NOT use markdown syntax like **, *, _, [text](url)):
- <b>...</b> for bold — headwords and lemmas that appear larger, darker, or in bold typeface. Lemmas can be enclosed in parentheses or brackets, e.g., <b>(*)abālu</b>, <b>[a]bātu</b>, <b>(parāsu)</b>, <b>[lemma]</b>, <b>(pa-ra-su)</b>.
- <i>...</i> for italic — Akkadian words in transliteration and lemmas that appear in italic typeface (not bold). Italic lemmas can also be in parentheses or brackets, e.g., <i>(parāsu)</i>, <i>[lemma]</i>, <i>(pa-ra-su)</i>.
- <sup>...</sup> for superscript characters (e.g., determinatives, note markers).
- <sub>...</sub> for subscript characters (e.g., index numbers like ₁ ₂ ₃).
- UPPERCASE → Sumerian logograms (e.g., DINGIR, LÚ) — keep as uppercase, no extra markup.
- LITERAL CHARACTERS: characters *, _, [, ], `, # are LITERAL when they appear in the source — output them verbatim, do NOT escape them, do NOT interpret as markdown. Examples: "lex.*" stays as "lex.*"; reconstructed forms like "*muḫḫû" keep the leading asterisk; "[broken]" stays as "[broken]".
- TAG HYGIENE: every opening tag MUST have a matching closing tag. Inline tags (<b>, <i>, <sup>, <sub>) close within the same <section>/<lex>/<bibliography>. Block tags (<entry>, <section>, <lex>, <bibliography>) must be properly nested — no orphan closers, no overlap.

LEXICAL vs BIBLIOGRAPHY — both are smaller-font paragraphs. Step 1 is always font size; step 2 is content type to choose between <lex> and <bibliography>:
- STEP 1 (font): if the paragraph is in noticeably smaller font than body, it is <lex> OR <bibliography> — never <section>. If it is body-font, it is <section> — regardless of content or position.
- STEP 2 (content): among smaller-font paragraphs, distinguish:
    - <lex>: bilingual Sumerian/Akkadian equivalences. Format includes Sumerian signs (e.g., "giš.úr.gaz = ..."), equation marks, and CAD lexical-source abbreviations (Hh., Nabnitu, Lu, Izi, Diri, Proto-Lu, An, Antagal, Erimhuš, etc.). Typically near the header, but a page may start with <lex> if the headword is on the previous page.
    - <bibliography>: modern secondary-literature citations in "Author, Work Year Page" format (e.g., "Bottéro, ARMT 7 312; Salonen Hausgeräte 2 141f."). Belongs at end of entry; a page may also start with <bibliography> if a previous entry's bibliography spills onto it.
- Body-font cross-references like "See also X", "Cf. X", "For the corr. form, see X" stay in a regular <section> — do NOT wrap them in <bibliography> even though their content looks bibliographic.

Output ONLY the tagged HTML. No explanations, no code fences, no markdown.""",
    "tei_lex0": _load_tei_lex0_prompt(),
    "ahw_refentry": """You are an expert Assyriologist specializing in Akkadian lexicography.
Perform high-precision OCR on the attached image containing a dictionary cross-reference entry from the AHw (Akkadisches Handwoerterbuch).

Language: Akkadian (transliterated). Content: Dictionary lemmas and cross-references.

STRICT EXTRACTION RULES:
1. Preserve diacritics: distinguish macrons (ā, ē, ī, ū), circumflexes (â, ê, î, û), and the glottal stop (ʾ).
2. Special consonants: preserve ḫ, š, ś, ṣ, ṭ, g̃ exactly — do not substitute with h, s, t, or g. The character g̃ (g with tilde) is a valid Akkadian consonant — never replace or alter it.
3. Parentheticals: maintain all parentheses exactly, e.g., (w)aʾāru(m).
4. Abbreviations and reference signs: preserve exactly as written.
5. No normalization: do not correct the spelling. Prioritize visual evidence over linguistic probability.
6. ONE LINE PER ENTRY: Each reference entry must be a single line. Never split an entry across multiple lines. Parts separated by semicolons (;) belong to the same entry — keep them on one line.
7. UNKNOWN SYMBOLS: If you encounter a small symbol, mark, or special character that you cannot confidently identify or map to a known Unicode character, output ↑ (U+2191) in its place. Do NOT guess or substitute with a visually similar but incorrect character. Common examples of such symbols are reference marks, cross-reference arrows, and determinative signs.

Output the result as plain text, one entry per line. No markdown, no explanations.""",
    "zettelkasten": """You are a specialist in Assyriology and Sumerian lexicography transcribing index cards from a digitized Zettelkasten (slip archive).

OUTPUT FORMAT
─────────────
Respond with ONE valid JSON object and NOTHING else — no preamble, no
explanation, and do NOT wrap the JSON in markdown fences. Escape every
double quote inside a string value as \\" (e.g. <span class=\\"red\\">).
The schema is:

{
  "lemma":   string | null,  // the headword (top-left, usually underlined), as HTML (see LEMMA rules). null only if the card has no headword.
  "content": string          // the FULL card transcribed as annotated HTML (see rules)
}

ALLOWED HTML TAGS (use ONLY these)
──────────────────────────────────
  • Color:        <span class="red">…</span>, <span class="green">…</span>
                  (black / normal typewriter text takes NO tag)
  • Underline:    <u>…</u>
  • Strikethrough: <s>…</s>
  • Superscript / determinatives: <sup>…</sup>   (e.g. <sup>d</sup>, <sup>ki</sup>,
                  <sup>mušen</sup>, <sup>túg</sup>, <sup>ŋiš</sup>, and superscript numbers)
  • Subscript:    <sub>…</sub>     (index numbers on signs: ka<sub>10</sub>, ka<sub>5</sub>, šuba<sub>x</sub>)
  • Italic:       <i>…</i>
  • Line break:   <br>
  • Transcriber note: <note>…</note>   (see NOTES rule)

LEMMA
─────
  • The lemma is the headword at the start of the card's first entry line,
    usually red and underlined, in the top-left corner.
  • Transcribe it as HTML using <u>, <sub>, <sup> as needed so determinatives
    and index numbers are preserved — e.g. é-<sup>d</sup>a-ba<sub>4</sub>,
    é-adab<sup>ki</sup>. Do NOT wrap the lemma in a color <span>.
  • "lemma" must carry exactly the same markup as the headword in "content":
    if the headword is underlined on the card, "lemma" keeps its <u>
    (e.g. <u>A</u>, never plain A).
  • A headword counts even if it is not underlined or is preceded by a note
    line (e.g. "SG ab 97 neu geschrieben" above "A → …"): "lemma" is then "A".
  • Set "lemma" to null ONLY when the card has no headword at all: a back,
    pure notes / bibliography, a blank card, or a card that starts directly
    with "→" and has nothing in the headword position. Never use a
    cross-reference target (the form after "→") as the lemma.

CONTENT
───────
  • Transcribe EVERYTHING on the card, top to bottom, left to right.
  • Wrap each visually distinct color: red typewriter lemmas and cross-references,
    green handwritten additions; black typewritten text takes no tag.
  • Keep underlines where the original underlines (lemmas, glosses, cross-ref targets).
  • Represent determinatives as <sup> (d, ki, mušen, túg, ŋiš, …) — do NOT
    flatten them to inline text or Unicode.

DO NOT COMPLETE OR ALTER THE TEXT
─────────────────────────────────
  • Transcribe EXACTLY what is on the card, including incomplete text.
  • NEVER close or complete an unclosed bracket, parenthesis, or quotation.
    If a reference is cut off or left unfinished (e.g. "(TH 527,"), transcribe
    it verbatim and STOP there — do not invent the missing part or add "…".
  • Do not normalize, expand abbreviations, or "fix" anything.

NOTES (transcriber observations)
────────────────────────────────
  • If you must record an observation that is NOT text written on the card
    (e.g. its position, that it is handwritten, or a layout remark), put it
    inside <note>…</note> — e.g. <note>handwritten, top right</note>.
  • Use <note> ONLY for such meta observations, never for actual card text.

SPECIAL CHARACTERS & UNCERTAINTY
────────────────────────────────
  • Preserve ALL diacritics exactly: ā ī ū ṭ ṣ ḫ š ŋ ĝ. Index numbers are
    always <sub>…</sub>, never Unicode subscript digits (₀–₉).
  • Keep arrows →, "bzw.", "s.v.", "o.Ü.", and checkmarks ✓ as-is.
  • The typewriter bracket sign overstruck with an x (a tall bracket with an
    x through it, used in pairs around a form, e.g. around saḫa<sub>x</sub>)
    is ALWAYS written ⟦ before the form and ⟧ after it:
    ⟦ <u>saḫa</u><sub>x</sub> ⟧. Never use †, *, ‡, ⌧, [x] or <s>[</s>.
  • If a reading is uncertain, append "(?)" immediately after it.
  • If text is illegible, write "???".

NOW output the JSON for the card image provided.""",
}

# Keys that cannot be deleted via the API
BUILTIN_PROMPT_KEYS: set[str] = set(PROMPTS.keys())

# Default prompt key
_default_prompt: str = "dictionary"


def get_default_prompt() -> str:
    return _default_prompt


def set_default_prompt(prompt_key: str) -> None:
    global _default_prompt
    if prompt_key in PROMPTS:
        _default_prompt = prompt_key
        logger.info(f"Default prompt set to: {prompt_key}")


def resolve_prompt(prompt: str | None) -> str:
    """Resolve a prompt parameter to actual prompt text.

    If `prompt` is a known key, return the stored text.
    If it looks like raw prompt text (>=30 chars and not a key), return as-is.
    Otherwise fall back to the default prompt.

    The 30-char threshold matches the frontend's CuReD `CUSTOM_OCR_PROMPT_MIN_LEN`.
    Keep them in sync — at the boundary the frontend sends the raw text and
    expects it to be treated as a raw prompt, not as a preset key.
    """
    if prompt and prompt not in PROMPTS and len(prompt) >= 30:
        return prompt
    key = prompt if prompt in PROMPTS else _default_prompt
    return PROMPTS[key]


# ── Multi-image batching ──
#
# Identity protocol: each image's segment is prefixed with a unique sentinel tag
# of the form [[IMG_001]], [[IMG_002]], ... We parse by extracting the block
# between consecutive tags. If a tag is missing or duplicated for a given slot,
# we mark that slot with `parse_status` so the caller can retry it individually
# — never by silent positional shift.

IMG_SENTINEL_PATTERN = re.compile(r'\[\[IMG_(\d{1,4})\]\]')

# Belt-and-suspenders: the previous delimiter format is still recognized as a
# fallback if the model ignored the sentinel instructions entirely. Even then,
# fail-soft: a count mismatch marks every slot for individual retry.
MULTI_IMAGE_DELIMITER = "===IMAGE_BREAK==="
_FALLBACK_SPLIT_PATTERNS = [
    r'\s*=+\s*IMAGE[\s_]*BREAK\s*=+\s*',        # ===IMAGE BREAK===, == IMAGE_BREAK ==
    r'\n\s*-{3,}\s*\n',                            # --- (horizontal rule)
    r'\n\s*={3,}\s*\n',                            # === (equals rule)
    r'\n\s*\[?Image\s+\d+\]?\s*:?\s*\n',          # Image 1: or [Image 1]
]


def _extract_boxed_segments(text: str, expected: int) -> List[str] | None:
    r"""Extract content from \boxed{} blocks (Qwen thinking-mode output).

    Returns a list of extracted segments if the count matches `expected`,
    otherwise None.
    """
    # Pattern 1: multiple \boxed{\text{content}} (one per image)
    text_matches = re.findall(r'\\boxed\{\\text\{(.+?)\}\}', text)
    if len(text_matches) == expected:
        return text_matches

    # Pattern 2: single \boxed{ ... } with one entry per line
    boxed_blocks = re.findall(r'\\boxed\{([^}]+)\}', text, re.DOTALL)
    if boxed_blocks:
        lines = []
        for block in boxed_blocks:
            for raw_line in block.split('\n'):
                clean = raw_line.strip().rstrip('\\').strip()
                # Strip literal \n that Qwen sometimes appends
                clean = re.sub(r'\\n$', '', clean).strip()
                if clean:
                    lines.append(clean)
        if len(lines) == expected:
            return lines

    return None


def _format_sentinel(idx_1_based: int) -> str:
    return f"[[IMG_{idx_1_based:03d}]]"


def wrap_prompt_for_batch(prompt: str, image_count: int) -> str:
    """Wrap a single-image OCR prompt for multi-image batch processing.
    Returns original prompt unchanged if image_count <= 1.

    Each image must be tagged with a per-image sentinel so the parser can
    map output segments back to images by identity, not position.
    """
    if image_count <= 1:
        return prompt

    first = _format_sentinel(1)
    second = _format_sentinel(2)
    last = _format_sentinel(image_count)
    tag_list = ", ".join(_format_sentinel(i) for i in range(1, image_count + 1))

    return (
        f"You are given {image_count} images, numbered 1 through {image_count} "
        f"in the order they appear in this message.\n\n"
        f"CRITICAL OUTPUT FORMAT — your response MUST follow this exact structure:\n"
        f"  - Begin image 1's output with the sentinel tag {first} on its own line.\n"
        f"  - Begin image 2's output with {second} on its own line.\n"
        f"  - Continue through image {image_count} with {last}.\n"
        f"  - The full list of required tags, in order, is:\n    {tag_list}\n"
        f"  - Output EVERY tag exactly once, even if an image's content is empty "
        f"(in that case, output the tag followed by a blank line).\n"
        f"  - Never reuse a tag. Never invent new tags. Do not output any text "
        f"before {first}.\n\n"
        f"Process each image independently using the instructions below.\n\n"
        f"Instructions for EACH image:\n{prompt}"
    )


def _parse_by_sentinels(
    response_text: str, image_count: int
) -> Tuple[List[str | None], Dict[str, Any]]:
    """Extract per-image segments using [[IMG_NNN]] sentinel tags.

    Returns (segments, diagnostics) where:
      - segments[i] is the text for image i+1, or None if no sentinel was found
        for that slot (slot must be retried individually)
      - diagnostics describes what happened: counts, missing/duplicate indices
    """
    matches = list(IMG_SENTINEL_PATTERN.finditer(response_text))

    # Bucket by index. Duplicate tags for the same index keep the first.
    by_idx: Dict[int, Tuple[int, int]] = {}  # idx -> (tag_end, next_start_or_eof)
    duplicates: List[int] = []
    out_of_range: List[int] = []

    for k, m in enumerate(matches):
        try:
            idx = int(m.group(1))
        except ValueError:
            continue
        if idx < 1 or idx > image_count:
            out_of_range.append(idx)
            continue
        # Segment runs from end of this tag to start of the NEXT tag in the
        # response (regardless of which index that next tag claims), or EOF.
        seg_start = m.end()
        seg_end = matches[k + 1].start() if k + 1 < len(matches) else len(response_text)
        if idx in by_idx:
            duplicates.append(idx)
            continue
        by_idx[idx] = (seg_start, seg_end)

    segments: List[str | None] = []
    missing: List[int] = []
    for i in range(1, image_count + 1):
        if i in by_idx:
            s, e = by_idx[i]
            segments.append(response_text[s:e])
        else:
            segments.append(None)
            missing.append(i)

    diagnostics: Dict[str, Any] = {
        "method": "sentinel",
        "tags_found": len(matches),
        "tags_expected": image_count,
        "missing_indices": missing,
        "duplicate_indices": duplicates,
        "out_of_range_indices": out_of_range,
    }
    return segments, diagnostics


def _parse_by_legacy_delimiter(
    response_text: str, image_count: int
) -> Tuple[List[str | None], Dict[str, Any]]:
    """Fallback parser for responses with no sentinels — uses the legacy
    delimiter and several regex fallbacks. Only used when no sentinels were
    found at all (model ignored the instructions).

    On any count mismatch returns segments=[None]*image_count so the caller
    re-runs every image individually rather than silently shifting content.
    """
    segments_text: List[str] = re.split(
        r'\s*' + re.escape(MULTI_IMAGE_DELIMITER) + r'\s*', response_text
    )
    method = "legacy_delimiter"
    if len(segments_text) != image_count:
        for pattern in _FALLBACK_SPLIT_PATTERNS:
            alt = re.split(pattern, response_text)
            if len(alt) == image_count:
                segments_text = alt
                method = "legacy_fallback"
                break

    if len(segments_text) != image_count:
        boxed = _extract_boxed_segments(response_text, image_count)
        if boxed is not None:
            return list(boxed), {
                "method": "boxed",
                "segments_found": len(boxed),
                "segments_expected": image_count,
            }

    diagnostics: Dict[str, Any] = {
        "method": method,
        "segments_found": len(segments_text),
        "segments_expected": image_count,
    }
    if len(segments_text) != image_count:
        # No reliable identity — force per-image retry for every slot.
        return [None] * image_count, diagnostics
    return list(segments_text), diagnostics


def parse_batch_response(
    response_text: str,
    image_count: int,
    image_dimensions: List[Tuple[int, int]],
) -> List[Dict[str, Any]]:
    """Split a multi-image VLM response into per-image results.

    Returns a list of length == image_count. Each entry is
        {"lines": [...], "dimensions": [...], "parse_status": "ok" | "missing_sentinel" |
         "duplicate_sentinel" | "no_identity"}
    plus a top-level "_batch_parse" diagnostics dict attached to results[0].

    Identity protocol: per-image sentinel tags [[IMG_NNN]]. A slot whose tag was
    missing or duplicated is returned with empty lines and a non-"ok" parse_status,
    so the caller can re-OCR it individually rather than accept a positional shift.
    """
    if image_count <= 1:
        lines = [line.strip() for line in response_text.split('\n') if line.strip()]
        w, h = image_dimensions[0] if image_dimensions else (0, 0)
        return [{"lines": lines, "dimensions": _estimate_dimensions(lines, w, h),
                 "parse_status": "ok"}]

    # Phase 1: try sentinel-based parsing (the authoritative method)
    segments, diagnostics = _parse_by_sentinels(response_text, image_count)
    tags_found = diagnostics.get("tags_found", 0)
    duplicate_set = set(diagnostics.get("duplicate_indices", []))

    # Phase 2: if NO sentinels at all, the model ignored the new protocol —
    # fall back to the legacy delimiter parser, but mark every slot non-ok if
    # the legacy parse fails. We never silently positional-shift.
    if tags_found == 0:
        legacy_segments, legacy_diag = _parse_by_legacy_delimiter(response_text, image_count)
        diagnostics = legacy_diag
        if all(seg is None for seg in legacy_segments):
            logger.warning(
                f"Batch response: 0 sentinels found AND legacy parse mismatch "
                f"({legacy_diag}); every slot will be retried individually"
            )
            results = []
            for i in range(image_count):
                w, h = image_dimensions[i] if i < len(image_dimensions) else (0, 0)
                results.append({
                    "lines": [], "dimensions": [],
                    "parse_status": "no_identity",
                })
            results[0]["_batch_parse"] = diagnostics
            return results
        segments = legacy_segments
        logger.warning(
            f"Batch response: no sentinels — falling back to legacy delimiter "
            f"(method={legacy_diag['method']}). Treat results with caution."
        )

    results: List[Dict[str, Any]] = []
    for i in range(image_count):
        seg = segments[i]
        idx_1based = i + 1
        w, h = image_dimensions[i] if i < len(image_dimensions) else (0, 0)
        if seg is None:
            status = "missing_sentinel"
            lines: List[str] = []
        else:
            lines = [line.strip() for line in seg.split('\n') if line.strip()]
            if idx_1based in duplicate_set:
                status = "duplicate_sentinel"
            else:
                status = "ok"
        results.append({
            "lines": lines,
            "dimensions": _estimate_dimensions(lines, w, h),
            "parse_status": status,
        })

    if diagnostics.get("missing_indices") or diagnostics.get("duplicate_indices") \
       or diagnostics.get("out_of_range_indices"):
        logger.warning(
            f"Batch response sentinel anomalies: {diagnostics} "
            f"(affected slots will be re-OCRed individually)"
        )

    results[0]["_batch_parse"] = diagnostics
    return results


def _estimate_dimensions(lines: list, image_width: int, image_height: int) -> list:
    """Generate evenly-spaced bounding boxes for text lines."""
    from entities.dimensions import Dimensions

    if not lines:
        return []
    line_height = image_height // max(1, len(lines))
    return [
        Dimensions(x=0, y=i * line_height, width=image_width, height=line_height)
        for i in range(len(lines))
    ]
