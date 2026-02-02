"""
Akkadian OCR Post-Processor

A rule-based post-processing service for OCR results that applies
Akkadian linguistic rules to fix common errors. Works with any OCR
engine (Kraken, VLM, etc.).
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class Correction:
    """Represents a single correction made to the text."""
    original: str
    corrected: str
    rule_type: str
    rule_description: str
    position: int


@dataclass
class ProcessingResult:
    """Result of post-processing a text."""
    original_text: str
    corrected_text: str
    corrections: List[Correction] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "original": self.original_text,
            "corrected": self.corrected_text,
            "corrections_count": len(self.corrections),
            "corrections": [
                {
                    "original": c.original,
                    "corrected": c.corrected,
                    "rule_type": c.rule_type,
                    "description": c.rule_description,
                    "position": c.position
                }
                for c in self.corrections
            ]
        }


class AkkadianPostProcessor:
    """
    Post-processor for Akkadian OCR results.

    Applies linguistic rules to fix common OCR errors based on
    Akkadian phonology and orthography.
    """

    RULES_FILE = Path(__file__).parent.parent / "config" / "akkadian_rules.json"

    def __init__(self, rules_path: Optional[Path] = None):
        self.rules_path = rules_path or self.RULES_FILE
        self.rules = self._load_rules()
        self._compile_patterns()
        logging.info(f"AkkadianPostProcessor initialized with {len(self._compiled_invalid_sequences)} invalid sequence rules")

    def _load_rules(self) -> dict:
        """Load rules from JSON file."""
        try:
            if self.rules_path.exists():
                with open(self.rules_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logging.warning(f"Rules file not found at {self.rules_path}, using empty rules")
                return self._get_default_rules()
        except Exception as e:
            logging.error(f"Error loading rules: {e}")
            return self._get_default_rules()

    def _get_default_rules(self) -> dict:
        """Return minimal default rules if file not found."""
        return {
            "invalid_sequences": {"rules": []},
            "character_confusions": {"rules": []},
            "custom_replacements": {"rules": []},
            "settings": {
                "case_sensitive": False,
                "log_corrections": True
            }
        }

    def _compile_patterns(self):
        """Pre-compile regex patterns for efficiency."""
        self._compiled_invalid_sequences = []

        # Compile invalid sequence patterns
        invalid_seq = self.rules.get("invalid_sequences", {}).get("rules", [])
        for rule in invalid_seq:
            pattern = rule.get("pattern", "")
            replacement = rule.get("replacement", "")
            description = rule.get("description", "")

            if pattern:
                flags = 0 if self.rules.get("settings", {}).get("case_sensitive", False) else re.IGNORECASE
                try:
                    compiled = re.compile(re.escape(pattern), flags)
                    self._compiled_invalid_sequences.append({
                        "pattern": compiled,
                        "original_pattern": pattern,
                        "replacement": replacement,
                        "description": description
                    })
                except re.error as e:
                    logging.warning(f"Invalid regex pattern '{pattern}': {e}")

    def reload_rules(self):
        """Reload rules from file (useful for runtime updates)."""
        self.rules = self._load_rules()
        self._compile_patterns()
        logging.info("Rules reloaded")

    def process_line(self, line: str) -> ProcessingResult:
        """
        Process a single line of OCR output.

        Args:
            line: The OCR output line to process

        Returns:
            ProcessingResult with original, corrected text and list of corrections
        """
        corrections = []
        corrected = line

        # Apply invalid sequence rules
        for rule in self._compiled_invalid_sequences:
            matches = list(rule["pattern"].finditer(corrected))
            for match in reversed(matches):  # Reverse to maintain positions
                original_text = match.group()
                replacement = rule["replacement"]

                # Preserve case if needed
                if not self.rules.get("settings", {}).get("case_sensitive", False):
                    if original_text.isupper():
                        replacement = replacement.upper()
                    elif original_text[0].isupper():
                        replacement = replacement[0].upper() + replacement[1:]

                corrections.append(Correction(
                    original=original_text,
                    corrected=replacement,
                    rule_type="invalid_sequence",
                    rule_description=rule["description"],
                    position=match.start()
                ))

                corrected = corrected[:match.start()] + replacement + corrected[match.end():]

        # Apply case normalization FIRST
        # Rule: Only UPPER-lower (with hyphen) is valid mixed case
        # Everything else should be normalized to lowercase
        case_norm = self.rules.get("case_normalization", {})
        if case_norm.get("enabled", False):
            def normalize_segment(segment):
                """Normalize a hyphen-separated segment."""
                # If all uppercase or all lowercase, keep as is
                # If mixed case, convert to lowercase
                has_upper = any(c.isupper() for c in segment)
                has_lower = any(c.islower() for c in segment)
                if has_upper and has_lower:
                    return segment.lower()
                return segment

            # Process the text preserving hyphens and other separators
            # Split by hyphen, normalize each segment, rejoin
            parts = corrected.split('-')
            normalized_parts = [normalize_segment(p) for p in parts]
            new_corrected = '-'.join(normalized_parts)

            if new_corrected != corrected:
                # Log the overall change
                corrections.append(Correction(
                    original=corrected,
                    corrected=new_corrected,
                    rule_type="case_normalization",
                    rule_description="Mixed case normalized (only UPPER-lower with hyphen is valid)",
                    position=0
                ))
                corrected = new_corrected

        # Apply custom replacements AFTER case normalization
        # This allows patterns like "dis" to match after "Dis" is normalized to "dis"
        custom_rules = self.rules.get("custom_replacements", {}).get("rules", [])
        for rule in custom_rules:
            pattern = rule.get("pattern", "")
            replacement = rule.get("replacement", "")
            description = rule.get("description", "Custom replacement")

            if pattern and pattern in corrected:
                pos = corrected.find(pattern)
                while pos != -1:
                    corrections.append(Correction(
                        original=pattern,
                        corrected=replacement,
                        rule_type="custom_replacement",
                        rule_description=description,
                        position=pos
                    ))
                    corrected = corrected[:pos] + replacement + corrected[pos + len(pattern):]
                    pos = corrected.find(pattern, pos + len(replacement))

        # Log corrections if enabled
        if self.rules.get("settings", {}).get("log_corrections", True) and corrections:
            logging.info(f"Post-processor made {len(corrections)} corrections: '{line}' → '{corrected}'")

        return ProcessingResult(
            original_text=line,
            corrected_text=corrected,
            corrections=corrections
        )

    def process_lines(self, lines: List[str]) -> List[ProcessingResult]:
        """
        Process multiple lines of OCR output.

        Args:
            lines: List of OCR output lines

        Returns:
            List of ProcessingResult objects
        """
        return [self.process_line(line) for line in lines]

    def process_text(self, text: str) -> ProcessingResult:
        """
        Process a full text (multiple lines as single string).

        Args:
            text: Full OCR output text

        Returns:
            ProcessingResult for the entire text
        """
        return self.process_line(text)

    def get_corrected_lines(self, lines: List[str]) -> List[str]:
        """
        Convenience method to get just the corrected lines.

        Args:
            lines: List of OCR output lines

        Returns:
            List of corrected lines
        """
        results = self.process_lines(lines)
        return [r.corrected_text for r in results]

    def add_rule(self, rule_type: str, rule: dict) -> bool:
        """
        Add a new rule at runtime.

        Args:
            rule_type: Type of rule ('invalid_sequences', 'custom_replacements', etc.)
            rule: Rule dictionary with pattern, replacement, description

        Returns:
            True if rule was added successfully
        """
        try:
            if rule_type not in self.rules:
                self.rules[rule_type] = {"rules": []}

            if "rules" not in self.rules[rule_type]:
                self.rules[rule_type]["rules"] = []

            self.rules[rule_type]["rules"].append(rule)
            self._compile_patterns()

            logging.info(f"Added new {rule_type} rule: {rule.get('pattern')} → {rule.get('replacement')}")
            return True
        except Exception as e:
            logging.error(f"Error adding rule: {e}")
            return False

    def save_rules(self) -> bool:
        """Save current rules to file."""
        try:
            with open(self.rules_path, 'w', encoding='utf-8') as f:
                json.dump(self.rules, f, indent=2, ensure_ascii=False)
            logging.info(f"Rules saved to {self.rules_path}")
            return True
        except Exception as e:
            logging.error(f"Error saving rules: {e}")
            return False

    def get_stats(self) -> dict:
        """Get statistics about loaded rules."""
        case_norm = self.rules.get("case_normalization", {})
        return {
            "invalid_sequences": len(self.rules.get("invalid_sequences", {}).get("rules", [])),
            "character_confusions": len(self.rules.get("character_confusions", {}).get("rules", [])),
            "custom_replacements": len(self.rules.get("custom_replacements", {}).get("rules", [])),
            "case_normalization_enabled": case_norm.get("enabled", False),
            "rules_file": str(self.rules_path),
            "settings": self.rules.get("settings", {})
        }


# Global instance for easy access
akkadian_post_processor = AkkadianPostProcessor()
