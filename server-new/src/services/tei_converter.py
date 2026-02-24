"""
TEI Lex-0 Converter

Orchestrates the conversion pipeline:
  OCR raw output → split entries → validate each → retry with correction prompt

Works with any VLM provider (DeepSeek, Gemini, Claude, Ollama) via the OCR factory.
"""

import re
import logging
from typing import List, Dict, Any, Optional, Callable

from services.tei_lex0_validator import tei_lex0_validator
from services.tei_prompt_builder import tei_prompt_builder

logger = logging.getLogger(__name__)

# Temperature schedule: decreasing on each retry for more deterministic corrections
RETRY_TEMPERATURES = [0.7, 0.3, 0.1]


class TeiConverter:
    """
    Converts raw VLM output into validated TEI Lex-0 entries.

    Usage:
        converter = TeiConverter()
        results = converter.convert_and_validate(
            raw_xml="<entry>...</entry><entry>...</entry>",
            retry_fn=my_retry_function,  # called to get corrected XML
            max_retries=3,
        )
    """

    def convert_and_validate(
        self,
        raw_xml: str,
        retry_fn: Optional[Callable] = None,
        max_retries: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Split raw VLM output into entries, validate each, retry if needed.

        Args:
            raw_xml: Raw XML output from VLM (may contain multiple entries)
            retry_fn: async/sync function(correction_prompt, temperature) -> corrected_xml
                      If None, no retries are attempted.
            max_retries: Maximum correction attempts per entry

        Returns:
            List of entry results:
            [
                {
                    "lemma": str,
                    "entry_type": str,
                    "xml": str,
                    "raw_content": str,
                    "status": "valid" | "error" | "warning",
                    "errors": [...],
                    "attempts": int,
                }
            ]
        """
        entries = self.split_entries(raw_xml)
        logger.info(f"Split raw output into {len(entries)} entries")

        results = []
        for i, entry_xml in enumerate(entries):
            result = self._validate_with_retry(entry_xml, i, retry_fn, max_retries)
            results.append(result)

        valid_count = sum(1 for r in results if r["status"] == "valid")
        error_count = sum(1 for r in results if r["status"] == "error")
        logger.info(f"Conversion complete: {valid_count} valid, {error_count} errors out of {len(results)} entries")

        return results

    def validate_single(self, entry_xml: str) -> Dict[str, Any]:
        """Validate a single entry without retries."""
        validation = tei_lex0_validator.validate_entry(entry_xml)
        return {
            "lemma": self.extract_lemma(entry_xml),
            "entry_type": self.extract_entry_type(entry_xml),
            "xml": entry_xml,
            "raw_content": self.extract_raw_content(entry_xml),
            "status": "valid" if validation["valid"] else "error",
            "errors": validation["errors"],
            "attempts": 1,
        }

    def _validate_with_retry(
        self,
        entry_xml: str,
        entry_index: int,
        retry_fn: Optional[Callable],
        max_retries: int,
    ) -> Dict[str, Any]:
        """Validate an entry and retry with correction prompt if it fails."""
        current_xml = entry_xml
        lemma = self.extract_lemma(current_xml)
        entry_type = self.extract_entry_type(current_xml)
        raw_content = self.extract_raw_content(current_xml)

        for attempt in range(max_retries + 1):
            validation = tei_lex0_validator.validate_entry(current_xml)

            if validation["valid"]:
                logger.info(f"Entry {entry_index} '{lemma}' valid after {attempt + 1} attempt(s)")
                return {
                    "lemma": lemma,
                    "entry_type": entry_type,
                    "xml": current_xml,
                    "raw_content": raw_content,
                    "status": "valid",
                    "errors": validation["errors"],  # may contain warnings
                    "attempts": attempt + 1,
                }

            # No retry function or exhausted retries
            if retry_fn is None or attempt >= max_retries:
                status = "error"
                # If only warnings remain, mark as warning
                if all(e["type"] == "warning" for e in validation["errors"]):
                    status = "warning"
                logger.warning(
                    f"Entry {entry_index} '{lemma}' has {len(validation['errors'])} issues "
                    f"after {attempt + 1} attempt(s)"
                )
                return {
                    "lemma": lemma,
                    "entry_type": entry_type,
                    "xml": current_xml,
                    "raw_content": raw_content,
                    "status": status,
                    "errors": validation["errors"],
                    "attempts": attempt + 1,
                }

            # Build correction prompt and retry
            temperature = RETRY_TEMPERATURES[min(attempt, len(RETRY_TEMPERATURES) - 1)]
            correction_prompt = tei_prompt_builder.build_correction_prompt(
                current_xml, validation["errors"]
            )

            logger.info(
                f"Entry {entry_index} '{lemma}' retry {attempt + 1}/{max_retries} "
                f"(temp={temperature}, {len(validation['errors'])} errors)"
            )

            try:
                corrected = retry_fn(correction_prompt, temperature)
                if corrected and corrected.strip():
                    # Extract entry from corrected output (VLM may add wrapper)
                    extracted = self._extract_entry_from_response(corrected)
                    if extracted:
                        current_xml = extracted
                    else:
                        current_xml = corrected.strip()
            except Exception as e:
                logger.error(f"Retry failed for entry {entry_index}: {e}")

        # Should not reach here
        return {
            "lemma": lemma,
            "entry_type": entry_type,
            "xml": current_xml,
            "raw_content": raw_content,
            "status": "error",
            "errors": [{"type": "error", "line": 1, "column": None, "message": "Max retries exceeded"}],
            "attempts": max_retries + 1,
        }

    # ─── Entry Splitting ──────────────────────────────────────────

    def split_entries(self, raw_xml: str) -> List[str]:
        """
        Split raw VLM output into individual <entry> elements.
        Uses a stack-based approach to handle nested entries.
        """
        # Strip markdown code fences if present
        raw_xml = self._strip_code_fences(raw_xml)

        entries = []
        pattern = re.compile(r"<entry[\s>]")

        pos = 0
        while pos < len(raw_xml):
            match = pattern.search(raw_xml, pos)
            if not match:
                break

            start = match.start()
            end = self._find_closing_tag(raw_xml, start, "entry")
            if end == -1:
                # No closing tag found, take rest of string
                entry = raw_xml[start:].strip()
                if entry:
                    entries.append(entry)
                break

            entries.append(raw_xml[start:end].strip())
            pos = end

        return entries

    @staticmethod
    def _find_closing_tag(xml: str, start_pos: int, tag_name: str) -> int:
        """Find the closing </tag> for an element, handling nesting."""
        depth = 0
        i = start_pos

        while i < len(xml):
            open_idx = xml.find(f"<{tag_name}", i)
            close_idx = xml.find(f"</{tag_name}>", i)

            if close_idx == -1:
                return -1

            if open_idx != -1 and open_idx < close_idx:
                # Check it's actually an opening tag
                if open_idx + len(tag_name) + 1 < len(xml):
                    char_after = xml[open_idx + len(tag_name) + 1]
                    if char_after in (" ", ">", "/"):
                        depth += 1
                i = open_idx + 1
            else:
                depth -= 1
                if depth == 0:
                    return close_idx + len(f"</{tag_name}>")
                i = close_idx + 1

        return -1

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove markdown code fences and XML declarations."""
        # Remove ```xml ... ``` fences
        text = re.sub(r"```(?:xml)?\s*\n?", "", text)
        # Remove XML declaration
        text = re.sub(r"<\?xml[^?]*\?>", "", text)
        return text.strip()

    @staticmethod
    def _extract_entry_from_response(text: str) -> Optional[str]:
        """Extract the first <entry>...</entry> from a VLM response."""
        text = TeiConverter._strip_code_fences(text)
        match = re.search(r"(<entry[\s>][\s\S]*?</entry>)", text)
        return match.group(1) if match else None

    # ─── Metadata Extraction ──────────────────────────────────────

    @staticmethod
    def extract_lemma(xml: str) -> str:
        """Extract lemma text from entry XML."""
        match = re.search(r'<orth[^>]*type="normalized"[^>]*>([^<]+)</orth>', xml)
        if match:
            return match.group(1).strip()
        # Fallback: try any <orth>
        match = re.search(r"<orth[^>]*>([^<]+)</orth>", xml)
        if match:
            return match.group(1).strip()
        # Fallback: use xml:id
        match = re.search(r'xml:id="([^"]+)"', xml)
        if match:
            return match.group(1)
        return "Unknown"

    @staticmethod
    def extract_entry_type(xml: str) -> str:
        """Extract entry type (mainEntry, ref) or POS."""
        match = re.search(r'type="(mainEntry|ref)"', xml)
        if match:
            return match.group(1)
        pos_match = re.search(r'<gram[^>]*type="pos"[^>]*>([^<]+)</gram>', xml)
        if pos_match:
            return pos_match.group(1).strip()
        return "unknown"

    @staticmethod
    def extract_raw_content(xml: str) -> str:
        """Extract <note type="rawContent"> text."""
        match = re.search(r'<note[^>]*type="rawContent"[^>]*>([\s\S]*?)</note>', xml)
        if match:
            return match.group(1).strip()
        return ""


# Global singleton
tei_converter = TeiConverter()
