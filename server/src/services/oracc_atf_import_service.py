"""
ORACC ATF Import Service

Parses ORACC-style ATF text and separates it into:
- Transliteration (eBL-ATF compatible content)
- Translation (English parallel translation)
- Lemmatization (#lem lines → TextLemmatization)

ORACC ATF format reference:
- Numbered lines: transliteration (e.g., "1. * ina {iti}BARA₂ ...")
- #lem: lines: lemmatization (e.g., "#lem: ina[by]PRP; amāt[command]N; ...")
- >> lines: parallel references (e.g., ">> A 1")
- #note: lines: scholarly notes
- @translation parallel en project: starts translation block
- $ lines: state/ruling lines (e.g., "$ single ruling")
- @ lines: structure (e.g., "@obverse", "@reverse")
"""

import hashlib
import logging
import re
from typing import List, Optional, Tuple

from entities.lemmatization import (
    TextLemmatization, LineLemmatization, LemmaAssignment
)

logger = logging.getLogger(__name__)

# Regex to parse ORACC lem entries: lemma[guideword]POS or +lemma[guideword]POS$form
ORACC_LEM_RE = re.compile(
    r'\+?'                          # optional leading +
    r'([^[\]]+?)'                   # lemma (non-greedy, up to [)
    r'\[([^\]]*)\]'                 # [guideword]
    r"([A-Z0-9']+)"                 # POS tag
    r'(?:\$([^\s;+]*))?'            # optional $form
)

# Line number pattern for transliteration lines
LINE_NUMBER_RE = re.compile(r'^(\d+[a-z]?(?:[-–]\d+)?(?:[\'′]+)?)\.\s+')


class OraccAtfImportService:
    """Parses ORACC ATF and extracts transliteration, translation, and lemmatization."""

    def parse(self, oracc_atf: str) -> dict:
        """
        Parse ORACC ATF text.

        Returns:
            {
                "identifier": str (P-number or publication),
                "identifier_type": str ("p_number" or "publication"),
                "transliteration": str (clean ATF for content field),
                "translation": str (English translation),
                "lemmatization_lines": list of (line_number, lem_entries),
                "metadata": dict (project, language, links, etc.)
            }
        """
        lines = oracc_atf.split('\n')

        identifier = ""
        identifier_type = "p_number"
        metadata = {}
        transliteration_lines = []
        translation_lines = []
        lem_data = []  # list of (line_number_str, raw_lem_str)

        in_translation = False
        last_text_line_number = ""

        for line in lines:
            stripped = line.strip()

            # Empty line
            if not stripped:
                if in_translation:
                    translation_lines.append("")
                continue

            # Header: &P363689 = TCL 06, 16
            if stripped.startswith('&'):
                identifier, identifier_type = self._parse_header(stripped)
                continue

            # Project/ATF directives
            if stripped.startswith('#project:'):
                metadata['project'] = stripped[len('#project:'):].strip()
                continue
            if stripped.startswith('#atf:'):
                metadata.setdefault('atf_directives', []).append(
                    stripped[len('#atf:'):].strip()
                )
                continue
            if stripped.startswith('#link:'):
                metadata.setdefault('links', []).append(
                    stripped[len('#link:'):].strip()
                )
                continue

            # Translation block
            if stripped.startswith('@translation'):
                in_translation = True
                continue

            if in_translation:
                # Structure lines within translation
                if stripped.startswith('@'):
                    # @obverse, @reverse, etc. in translation — skip
                    continue
                if stripped.startswith('$'):
                    translation_lines.append(stripped)
                    continue
                # Translation text lines: "1. (If) in Nisannu..."
                translation_lines.append(stripped)
                continue

            # Lemmatization line
            if stripped.startswith('#lem:'):
                raw_lem = stripped[len('#lem:'):].strip()
                lem_data.append((last_text_line_number, raw_lem))
                continue

            # Note line — include in transliteration as comment
            if stripped.startswith('#note:'):
                transliteration_lines.append(stripped)
                continue

            # Parallel reference — skip (not part of eBL-ATF)
            if stripped.startswith('>>'):
                continue

            # Other comment lines (#)
            if stripped.startswith('#'):
                # Skip other ORACC-specific comments
                continue

            # Structure lines (@obverse, @reverse, @tablet, @top, @colophon, @catchline, etc.)
            if stripped.startswith('@'):
                transliteration_lines.append(stripped)
                continue

            # State lines ($ single ruling, $ rest broken, etc.)
            if stripped.startswith('$'):
                transliteration_lines.append(stripped)
                continue

            # Text lines (numbered)
            match = LINE_NUMBER_RE.match(stripped)
            if match:
                last_text_line_number = match.group(1) + '.'
                transliteration_lines.append(stripped)
                continue

            # Catchline, colophon, or other unnumbered text
            transliteration_lines.append(stripped)

        return {
            "identifier": identifier,
            "identifier_type": identifier_type,
            "transliteration": '\n'.join(transliteration_lines),
            "translation": '\n'.join(translation_lines),
            "lemmatization_lines": lem_data,
            "metadata": metadata,
        }

    def build_lemmatization(
        self,
        production_id: int,
        transliteration: str,
        lem_data: List[Tuple[str, str]],
        dictionary=None
    ) -> Optional[TextLemmatization]:
        """
        Convert ORACC #lem data into TextLemmatization.

        Each #lem line is matched to its corresponding transliteration line.
        Uses content-aware alignment: verifies each lem↔token pair by checking
        if the resolved eBL ID is compatible with the token's logogram/word
        candidates, rather than relying on pure positional matching.

        ORACC format: lemma[guideword]POS; lemma[guideword]POS; ...
        """
        if not lem_data:
            return None

        content_hash = hashlib.md5(transliteration.encode('utf-8')).hexdigest()

        # Parse transliteration to get text lines and their tokens
        text_lines = self._extract_text_lines(transliteration)

        # Pre-resolve all lem entries to eBL IDs
        resolved_entries = []  # list of (lemma, guideword, pos, ebl_id_or_fallback, is_resolved)
        for _, raw_lem in lem_data:
            line_entries = []
            for lemma, guideword, pos in self._parse_lem_line(raw_lem):
                ebl_id = None
                if lemma and lemma not in ('X', 'u', 'n', 'x') and dictionary:
                    ebl_id = dictionary.resolve_oracc_lemma(lemma, guideword, pos)
                line_entries.append((lemma, guideword, pos, ebl_id))
            resolved_entries.append(line_entries)

        # Build lemmatization lines with content-aware alignment
        lem_lines = []
        lem_idx = 0
        resolved_count = 0
        total_count = 0

        for line_number, line_content in text_lines:
            if lem_idx >= len(lem_data):
                break

            lem_line_number, _ = lem_data[lem_idx]

            # Match by line number
            if lem_line_number and line_number and lem_line_number != line_number:
                continue

            lem_entries = resolved_entries[lem_idx]
            tokens = self._extract_tokens(line_content)

            # Content-aware alignment: match lem entries to tokens
            assignments = self._align_lem_to_tokens(
                tokens, lem_entries, dictionary
            )

            # Count stats
            for a in assignments:
                if a.oracc_citation:
                    total_count += 1
                    if a.unique_lemma and '(' not in a.unique_lemma[0]:
                        resolved_count += 1

            lem_lines.append(LineLemmatization(
                line_number=line_number,
                tokens=assignments
            ))
            lem_idx += 1

        if not lem_lines:
            return None

        logger.info(f"ORACC lemmatization: {resolved_count}/{total_count} lemmas resolved to eBL IDs")

        return TextLemmatization(
            production_id=production_id,
            content_hash=content_hash,
            lines=lem_lines,
            ai_suggested=False
        )

    def _align_lem_to_tokens(
        self,
        tokens: List[str],
        lem_entries: List[tuple],
        dictionary
    ) -> List[LemmaAssignment]:
        """
        Content-aware alignment of lem entries to tokens.

        For each lem entry, checks if its resolved eBL ID is compatible
        with the current token (via logogram or word lookup). If not,
        skips the token (assigns empty) and tries the next one.
        This handles cases where ORACC and our tokenizer disagree on
        what counts as a word (e.g., determinative grouping).
        """
        assignments = []
        entry_idx = 0

        for token in tokens:
            if entry_idx >= len(lem_entries):
                # No more lem entries — remaining tokens get empty assignments
                assignments.append(LemmaAssignment(value=token, unique_lemma=[]))
                continue

            lemma, guideword, pos, ebl_id = lem_entries[entry_idx]

            # Check if this lem entry is compatible with this token
            if ebl_id and dictionary and not self._is_compatible(token, ebl_id, dictionary):
                # Mismatch — maybe this token should be skipped (e.g., standalone determinative)
                # Look ahead: does the NEXT token match this lem entry?
                next_token_idx = tokens.index(token) + 1 if token in tokens else -1
                if next_token_idx > 0 and next_token_idx < len(tokens):
                    next_token = tokens[next_token_idx]
                    if self._is_compatible(next_token, ebl_id, dictionary):
                        # Next token matches — skip current token with empty assignment
                        assignments.append(LemmaAssignment(value=token, unique_lemma=[]))
                        continue

            # Assign this lem entry to this token
            unique_lemma = []
            is_suggestion = False
            if lemma and lemma not in ('X', 'u', 'n', 'x'):
                if ebl_id:
                    unique_lemma = [ebl_id]
                    is_suggestion = True
                else:
                    unique_lemma = [f"{lemma} ({guideword}) [{pos}]"]
                    is_suggestion = True

            assignments.append(LemmaAssignment(
                value=token,
                unique_lemma=unique_lemma,
                is_suggestion=is_suggestion,
                suggestion_source="atf_import" if is_suggestion else "",
                oracc_guideword=guideword if is_suggestion else "",
                oracc_citation=lemma if is_suggestion else "",
                oracc_pos=pos if is_suggestion else "",
            ))
            entry_idx += 1

        return assignments

    def _is_compatible(self, token: str, ebl_id: str, dictionary) -> bool:
        """
        Check if a resolved eBL lemma ID is compatible with a token.
        Uses logogram lookup for uppercase tokens, word lookup for lowercase.
        """
        # Strip brackets and damage markers from token for lookup
        clean = re.sub(r'[\[\]()<>°\\#?!*]', '', token)
        # Strip determinatives
        clean = re.sub(r'\{[^}]+\}', '', clean).strip()
        if not clean:
            return False

        # Check if token looks like a logogram (uppercase)
        alpha = re.sub(r'[₀-₉ₓ0-9.\-]', '', clean)
        if alpha and alpha == alpha.upper() and alpha.isalpha():
            # Logogram: check logogram index
            candidates = dictionary.lookup_logogram(clean)
            if ebl_id in candidates:
                return True
            # Also try without subscript normalization issues
            # Strip phonetic complements (lowercase suffixes after -)
            logo_part = re.sub(r'[-.]?[a-zšṣṭḫāēīūâêîûĝ][a-zšṣṭḫāēīūâêîûĝ₀₁₂₃₄₅₆₇₈₉ₓ0-9]*$', '', clean)
            if logo_part and logo_part != clean:
                candidates = dictionary.lookup_logogram(logo_part)
                if ebl_id in candidates:
                    return True

        # Syllabic/Akkadian: check word index
        candidates, _ = dictionary.lookup_with_level(clean)
        if ebl_id in candidates:
            return True

        # Check with joined syllables
        joined = dictionary._join_syllables(clean.lower())
        candidates = dictionary._index.get(joined, [])
        if ebl_id in candidates:
            return True

        # Normalized check
        normalized = joined.translate(dictionary.VOWEL_NORMALIZE)
        candidates = dictionary._index.get(normalized, [])
        if ebl_id in candidates:
            return True

        return False

    def _parse_header(self, header: str) -> Tuple[str, str]:
        """Parse &P363689 = TCL 06, 16 → identifier + type."""
        # Strip the &
        header = header.lstrip('&').strip()

        # Split on =
        parts = header.split('=', 1)

        p_number = parts[0].strip()
        publication = parts[1].strip() if len(parts) > 1 else ""

        # If it starts with P followed by digits, it's a P-number
        if re.match(r'^P\d+', p_number):
            return p_number, "p_number"
        elif publication:
            return publication, "publication"
        else:
            return p_number, "publication"

    def _parse_lem_line(self, raw_lem: str) -> List[Tuple[str, str, str]]:
        """
        Parse ORACC #lem line into list of (lemma, guideword, POS).

        Format: lemma[guideword]POS; lemma[guideword]POS; ...
        Examples:
            ina[by]PRP
            amāt[command]N
            +Nergal[1]DN$
            bibbu[planet]N
        """
        entries = []
        # Split on ; (with optional whitespace and +.)
        parts = re.split(r'\s*;\s*', raw_lem)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Remove trailing "+." (sentence boundary marker)
            part = re.sub(r'\s*\+?\.\s*$', '', part)
            if not part:
                continue

            match = ORACC_LEM_RE.match(part)
            if match:
                lemma = match.group(1).strip().lstrip('+')
                guideword = match.group(2).strip()
                pos = match.group(3).strip()
                entries.append((lemma, guideword, pos))
            else:
                # Fallback: treat as unknown
                entries.append((part, '', ''))

        return entries

    def _extract_text_lines(self, transliteration: str) -> List[Tuple[str, str]]:
        """
        Extract numbered text lines from transliteration.
        Returns list of (line_number, content).
        """
        result = []
        for line in transliteration.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            # Skip structure/state/comment lines
            if stripped.startswith(('@', '$', '#')):
                continue
            match = LINE_NUMBER_RE.match(stripped)
            if match:
                line_num = match.group(1) + '.'
                content = stripped[match.end():]
                result.append((line_num, content))
        return result

    def _extract_tokens(self, line_content: str) -> List[str]:
        """
        Extract lemmatizable tokens from a transliteration line.
        Skips determinatives, numbers in isolation, and non-word tokens.
        """
        tokens = []
        for part in line_content.split():
            # Skip language shifts
            if part.startswith('%'):
                continue
            # Skip ellipsis and single signs
            if part in ('...', 'x', 'X', '$', '||', '|'):
                continue
            tokens.append(part)
        return tokens


# Singleton
oracc_import_service = OraccAtfImportService()
