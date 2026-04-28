"""
ATF Tokenizer Service

Parses raw ATF text into structured tokens for lemmatization.
This is a lightweight tokenizer focused on extracting word-level tokens,
not a full grammar parser (see ebl_atf_parser.py for that).
"""

import hashlib
import re
import logging
from typing import List, Tuple

from entities.lemmatization import AtfToken, AtfLine, TokenizedText

logger = logging.getLogger(__name__)

# Regex for ATF line number prefix: "1.", "1'.", "1''.", "1a.", "a+1.", "1-3.", etc.
LINE_NUMBER_RE = re.compile(r'^([a-z]\+)?\d+[a-z]?(?:[-–]\d+)?(?:[\'′]+)?(?:\.\s*)')

# Regex for damage/uncertainty flags at the end of a token
FLAGS_RE = re.compile(r'[#?!*]+$')

# Regex for subscript digits (Unicode subscript numerals ₀-₉ and ₓ)
SUBSCRIPT_RE = re.compile(r'[\u2080-\u2089\u2093]')

# Regex to detect determinatives: {d}, {m}, {f}, {ki}, etc.
DETERMINATIVE_RE = re.compile(r'^\{[^}]+\}$')

# Regex to detect tokens that are purely determinative-wrapped: {d}AMAR.UTU
STARTS_WITH_DET_RE = re.compile(r'^\{[^}]+\}')

# Regex to detect numbers: pure digits, or digit+sign patterns like 1(diš)
NUMBER_RE = re.compile(r'^\d+(\([^)]+\))?$')

# Tokens that are not words and should not be lemmatized
SKIP_TOKENS = {'...', 'x', 'X', '$', '||', '|'}


class AtfTokenizer:
    """Tokenizes ATF text into structured lines and tokens."""

    def tokenize(self, atf_text: str) -> TokenizedText:
        """Parse ATF text into TokenizedText with lines and tokens."""
        content_hash = hashlib.md5(atf_text.encode('utf-8')).hexdigest()
        lines = []

        for i, raw_line in enumerate(atf_text.split('\n')):
            stripped = raw_line.strip()
            line_type = self._classify_line(stripped)

            if line_type == "text":
                line_number, tokens = self._parse_text_line(stripped)
                lines.append(AtfLine(
                    line_number=line_number,
                    raw_text=raw_line,
                    tokens=tokens,
                    line_type="text",
                    atf_index=i
                ))
            else:
                lines.append(AtfLine(
                    line_number="",
                    raw_text=raw_line,
                    tokens=[],
                    line_type=line_type,
                    atf_index=i
                ))

        return TokenizedText(lines=lines, content_hash=content_hash)

    def _classify_line(self, line: str) -> str:
        """Classify an ATF line by type."""
        if not line:
            return "empty"
        if line.startswith('@'):
            return "structure"
        if line.startswith('$'):
            return "state"
        if line.startswith('#'):
            return "comment"
        if line.startswith('//'):
            return "parallel"
        # Check if it starts with a line number pattern
        if LINE_NUMBER_RE.match(line):
            return "text"
        # Could be a continuation or unrecognized — treat as text if it has content
        return "text"

    def _parse_text_line(self, line: str) -> Tuple[str, List[AtfToken]]:
        """Parse a text line into line number and tokens."""
        # Extract line number
        match = LINE_NUMBER_RE.match(line)
        if match:
            line_number = match.group(0).strip()
            content = line[match.end():]
        else:
            line_number = ""
            content = line

        # Handle language shifts — strip %akk, %sux, etc. from tokens
        # They appear inline: "%sux lugal-e %akk LUGAL"
        tokens = []
        raw_parts = content.split()
        token_index = 0

        in_broken = False  # Track if we're inside [...]

        for part in raw_parts:
            # Skip language shift markers
            if part.startswith('%'):
                continue

            # Skip commentary protocol markers
            if part in ('!qt', '!bs', '!cm', '!zz'):
                continue

            # Track broken context
            if '[' in part:
                in_broken = True
            if ']' in part:
                was_broken = True
            else:
                was_broken = False

            # Skip non-lemmatizable tokens
            if part in SKIP_TOKENS:
                token_index += 1
                if was_broken and ']' in part:
                    in_broken = False
                continue

            token = self._parse_token(part, token_index, in_broken)
            tokens.append(token)
            token_index += 1

            if was_broken:
                in_broken = False

        return line_number, tokens

    def _parse_token(self, raw: str, index: int, in_broken: bool) -> AtfToken:
        """Parse a single token string into an AtfToken."""
        # Step 1: Strip brackets first so [{giš}TUKUL → {giš}TUKUL
        no_brackets = re.sub(r'[\[\]()<>°\\]', '', raw)

        # Step 2: Strip determinative prefixes/suffixes (e.g., {d}UTU -> UTU)
        stripped_det = STARTS_WITH_DET_RE.sub('', no_brackets)
        stripped_det = re.sub(r'\{[^}]+\}$', '', stripped_det)
        # Also strip any remaining curly braces (e.g., from nested brackets)
        cleaned = re.sub(r'\{[^}]*\}', '', stripped_det)

        # Step 3: Strip ALL damage/uncertainty flags (can appear after any sign, not just at end)
        cleaned = re.sub(r'[#?!*]', '', cleaned)

        # Step 4: Strip subscript/index digits for lookup
        # Handles both Unicode subscripts (li₂ → li) and ASCII indices (li2 → li, i3 → i)
        # ASCII indices appear after syllables: strip digits that follow letters
        cleaned_no_sub = SUBSCRIPT_RE.sub('', cleaned)
        cleaned_no_sub = re.sub(r'(?<=[a-zA-ZšṣṭḫĝŠṢṬḪĜāēīūâêîûĀĒĪŪÂÊÎÛ])\d+', '', cleaned_no_sub)

        # Detect properties
        is_determinative = bool(DETERMINATIVE_RE.match(no_brackets))
        is_number = bool(NUMBER_RE.match(cleaned))
        is_damaged = '#' in raw
        is_uncertain = '?' in raw
        is_broken = in_broken or '[' in raw

        # Detect logograms: all uppercase (after stripping dots, hyphens, digits, subscripts)
        # E.g., E₂.GAL → EGAL, LUGAL → LUGAL, GU₄.HI.A → GUHIA
        # Also detect mixed case as logogram+phonogram: E₂.GAL-li-im has uppercase part
        logo_check = cleaned.replace('.', '').replace('-', '')
        logo_alpha = re.sub(r'[0-9]', '', SUBSCRIPT_RE.sub('', logo_check))
        is_logogram = bool(logo_alpha) and logo_alpha == logo_alpha.upper() and logo_alpha.isalpha()

        # Mixed case: logogram with phonetic complement (E₂.GAL-li-im, LUGAL-šu)
        # Detect if there's a significant uppercase portion
        if not is_logogram and logo_alpha:
            upper_chars = [c for c in logo_alpha if c.isupper()]
            lower_chars = [c for c in logo_alpha if c.islower()]
            if len(upper_chars) >= 2 and upper_chars:
                is_logogram = True

        return AtfToken(
            index=index,
            raw=raw,
            cleaned=cleaned_no_sub if cleaned_no_sub else cleaned,
            is_determinative=is_determinative,
            is_number=is_number,
            is_damaged=is_damaged,
            is_uncertain=is_uncertain,
            is_broken=is_broken,
            is_logogram=is_logogram,
        )
