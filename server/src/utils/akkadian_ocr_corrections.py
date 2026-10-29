"""
Post-OCR corrections for Akkadian / Assyriological dictionary text.

Applied automatically after OCR and before text is sent to CuReD or saved
in batch recognition.  Rules are deliberately conservative: they target
common, unambiguous mis-readings that every VLM produces on AHw/CAD scans.
"""
import re
import logging
from typing import List

logger = logging.getLogger(__name__)

# Vowels that may surround the glottal stop ʾ
_VOWELS = set("aeiouAEIOUāēīūâêîûÂÊÎÛĀĒĪŪàèìùäëïü")
_V = "[" + re.escape("".join(_VOWELS)) + "]"

# One or more ASCII apostrophes / quotes between vowels → same count of ʾ
# e.g.  a'aru → aʾaru,  wu''urtum → wuʾʾurtum
_APOSTROPHES_RE = re.compile(
    r"(?<=" + _V + r")"                    # lookbehind: vowel
    r"(['\u2018\u2019\u0060\u00B4]+)"      # one or more apostrophe-like chars
    r"(?=" + _V + r")"                      # lookahead: vowel
)

# Orphaned characters that are misrecognised reference signs (↑)
# Heuristic: a standalone character surrounded by whitespace / line-start /
# line-end, optionally followed by a period.  We avoid replacing "d" when it
# is part of a word (e.g. "dāru").
# d q ɗ ⊃ ḫ δ ◌ ʿ Ə ə ʾ ɑ ḏ ą ʾq ʿd ¢ ʔ ⁗ Ɒ ↽ ◂ ⊲ Ⅎ ⱴ ≗ ⸗ ℘ ḍ ℴ ⁜ ⁑ Ɐ ⊳ ꓥ ↟
# ᵈ ʿq ℩ ℺ ℆ ⱸ Ɐ ℒ (◂ Ɑ Ɒ(U+2C70) ꞈ ⊊ ℭ ℸ ↸ ℨ ⱡ ⱺ ⱥ ℁ ⁕ ≬ ꓒ ⱶ
# ↿ ¤ 🡙 ⟐ ₫ ↤ ⸮ 🝖 ℗ Å 🜚 ℀ ~ ℮ ⚥ ↁ 🜔 ⚹

# Shared single-char class for all orphaned reference-sign characters
_REF_CHARS = (
    r"[q\u0257\u2283ḫ\u03B4\u25CC\u02BF\u018F\u0259\u02BE\u0251\u1E0F\u0105\u00A2\u0294\u2057"
    r"\u0252\u21BD\u25C2\u22B2\u2132\u2C74\u2257\u2E17\u2118\u1E0D\u2134\u205C\u2051\u0250\u22B3\uA4E5\u219F"
    r"\u1D48\u2129\u213A\u2106\u2C78\u2C6F\u2112\u2C6D\u2C70\uA788\u228A\u212D\u2138\u21B8\u2128\u2C61\u2C7A\u2C65"
    r"\u2101\u2055\u226C\uA4D2\u2C76\u21BF\u00A4\U0001F859\u27D0\u20AB\u21A4\u2E2E\U0001F756\u2117"
    r"\u00C5\U0001F71A\u2100\u212E\u26A5\u2181\U0001F714\u26B9"
    r"\u201C\u2190\u2E1A\u1D05\u16EB\u2E26\u0111\u2BA9\u2E2C]"
)
# Multi-char alternatives
_REF_MULTI = r"\u02BEq|\u02BFd|\u02BFq|\(\u25C2"

_REF_SIGN_RE = re.compile(
    r"(?:^|(?<=\s))"       # start-of-string or preceded by whitespace
    r"(" + _REF_MULTI + r"|" + _REF_CHARS + r")\.?"
    r"(?=\s|$)"             # followed by whitespace or end-of-string
)

# Paren variant: same as _REF_CHARS but excluding q, ḫ, ʾ (U+02BE), ᵈ (U+1D48)
# which can appear legitimately inside parentheses in AHw notation
_REF_CHARS_PAREN = (
    r"[\u0257\u2283\u03B4\u25CC\u02BF\u018F\u0259\u0251\u1E0F\u0105\u00A2\u0294\u2057"
    r"\u0252\u21BD\u25C2\u22B2\u2132\u2C74\u2257\u2E17\u2118\u1E0D\u2134\u205C\u2051\u0250\u22B3\uA4E5\u219F"
    r"\u2129\u213A\u2106\u2C78\u2C6F\u2112\u2C6D\u2C70\uA788\u228A\u212D\u2138\u21B8\u2128\u2C61\u2C7A\u2C65"
    r"\u2101\u2055\u226C\uA4D2\u2C76\u21BF\u00A4\U0001F859\u27D0\u20AB\u21A4\u2E2E\U0001F756\u2117"
    r"\u00C5\U0001F71A\u2100\u212E\u26A5\u2181\U0001F714\u26B9"
    r"\u201C\u2190\u2E1A\u1D05\u16EB\u2E26\u0111\u2BA9\u2E2C]"
)

# Ref-sign character right after ( or before ) → replace char only, keep paren
_REF_SIGN_PAREN_RE = re.compile(
    r"(?<=\()(" + _REF_MULTI + r"|" + _REF_CHARS_PAREN + r")\.?"
    r"|"
    r"(" + _REF_MULTI + r"|" + _REF_CHARS_PAREN + r")\.?(?=\))"
)


# Double pipe || → double vertical line ‖
_DOUBLE_PIPE_RE = re.compile(r"\|\|")

# Double comma → German opening quote „
_DOUBLE_COMMA_RE = re.compile(r",,")

# Straight double-quote closing a „ → German closing quote "
# Matches „...text..." and replaces only the closing " with "
_GERMAN_QUOTE_PAIR_RE = re.compile(r'(„[^""]*)"')


def _replace_apostrophes(m: re.Match) -> str:
    """Replace each apostrophe-like char with ʾ, preserving count."""
    return "ʾ" * len(m.group(1))



def correct_line(line: str) -> str:
    """Apply all Akkadian OCR corrections to a single line."""
    original = line

    # 1. Apostrophes between vowels → glottal stop(s) ʾ
    line = _APOSTROPHES_RE.sub(_replace_apostrophes, line)

    # 2. Orphaned q / ɗ / ⊃ / ḫ etc. → ↑ (reference sign)
    line = _REF_SIGN_RE.sub("↑", line)

    # 2b. Ref-sign chars adjacent to parentheses → ↑ (keep the paren)
    line = _REF_SIGN_PAREN_RE.sub("↑", line)

    # 3. || → ‖
    line = _DOUBLE_PIPE_RE.sub("‖", line)

    # 4. Double comma → German opening quote „
    line = _DOUBLE_COMMA_RE.sub("„", line)

    # 5. Straight " closing a „ → German closing quote "
    line = _GERMAN_QUOTE_PAIR_RE.sub('\\1\u201c', line)

    if line != original:
        logger.debug(f"OCR correction: '{original}' → '{line}'")

    return line


def _is_new_entry(line: str) -> bool:
    """Detect whether a line starts a new dictionary entry (not a continuation).

    New entries are signalled by:
    - Leading whitespace (indentation)
    - Bold headword at start: **lemma** or **(lemma)** etc.
    - Empty line
    """
    if not line:
        return True
    if line[0] in (" ", "\t"):
        return True
    # Bold headword at start of line (markdown **...**)
    if line.startswith("**"):
        return True
    return False


def _join_wrapped_lines(lines: List[str]) -> List[str]:
    """Join soft-wrapped lines into paragraphs.

    Dictionary columns wrap long entries across multiple lines.  A real new
    paragraph / entry is signalled by indentation, a bold headword (**...**),
    or an empty line.  Lines that don't match these patterns are continuations
    of the previous line and get joined with a single space.
    """
    if not lines:
        return lines

    merged: List[str] = [lines[0]]
    for line in lines[1:]:
        if _is_new_entry(line):
            merged.append(line)
        else:
            # Continuation of previous line
            merged[-1] = merged[-1].rstrip() + " " + line.lstrip()
    return merged


def correct_lines(lines: List[str]) -> List[str]:
    """Apply Akkadian OCR corrections to a list of OCR output lines."""
    lines = _join_wrapped_lines(lines)
    return [correct_line(line) for line in lines]
