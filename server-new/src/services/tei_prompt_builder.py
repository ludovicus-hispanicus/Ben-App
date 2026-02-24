"""
TEI Lex-0 Prompt Builder

Assembles the full system prompt from the template + gold-standard examples.
Also builds correction prompts for retry loops.
"""

import logging
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts" / "tei_lex0"
EXAMPLES_DIR = PROMPTS_DIR / "examples"

EXAMPLE_FILES = [
    "01-qabux_1_ahw.xml",
    "02-qalqa-lu_ahw.xml",
    "03-qardamu_ahw.xml",
]


class TeiPromptBuilder:
    """Builds TEI Lex-0 prompts with gold-standard examples."""

    def __init__(self):
        self._system_prompt_cache = None

    def build_system_prompt(self) -> str:
        """
        Load system-prompt.txt and inject gold examples at {{EXAMPLES}}.
        Result is cached after first build.
        """
        if self._system_prompt_cache is not None:
            return self._system_prompt_cache

        template_path = PROMPTS_DIR / "system-prompt.txt"
        if not template_path.exists():
            logger.error(f"System prompt template not found at {template_path}")
            return self._fallback_prompt()

        template = template_path.read_text(encoding="utf-8")
        examples = self._load_examples()
        self._system_prompt_cache = template.replace("{{EXAMPLES}}", examples)

        logger.info(
            f"Built TEI Lex-0 system prompt: {len(self._system_prompt_cache)} chars, "
            f"{len(examples.split('---'))} examples"
        )
        return self._system_prompt_cache

    def build_correction_prompt(
        self, previous_xml: str, errors: List[Dict]
    ) -> str:
        """
        Build a correction prompt with the failed XML and validation errors.
        """
        template_path = PROMPTS_DIR / "correction-prompt.txt"
        if not template_path.exists():
            # Inline fallback
            return (
                f"The following XML entry failed validation. Fix the errors.\n\n"
                f"## Previous XML\n\n{previous_xml}\n\n"
                f"## Errors\n\n" +
                "\n".join(
                    f"- [{e.get('type', 'error')}] Line {e.get('line', 1)}: {e.get('message', '')}"
                    for e in errors
                )
            )

        template = template_path.read_text(encoding="utf-8")

        error_text = "\n".join(
            f"- [{e.get('type', 'error')}] Line {e.get('line', 1)}: {e.get('message', '')}"
            for e in errors
        )

        return (
            template
            .replace("{{PREVIOUS_XML}}", previous_xml)
            .replace("{{ERRORS}}", error_text)
        )

    def _load_examples(self) -> str:
        """Load gold-standard XML examples from the examples directory."""
        if not EXAMPLES_DIR.exists():
            logger.warning(f"Examples directory not found at {EXAMPLES_DIR}")
            return "(No gold-standard examples available — use your best judgment based on the rules above.)"

        examples = []
        for filename in EXAMPLE_FILES:
            filepath = EXAMPLES_DIR / filename
            if filepath.exists():
                content = filepath.read_text(encoding="utf-8").strip()
                examples.append(f"### Example: {filename}\n\n{content}")
            else:
                logger.warning(f"Example file not found: {filepath}")

        if not examples:
            return "(No gold-standard examples available — use your best judgment based on the rules above.)"

        return "\n\n---\n\n".join(examples)

    @staticmethod
    def _fallback_prompt() -> str:
        """Minimal fallback prompt if template files are missing."""
        return (
            "You are an expert in digitizing Assyriological dictionaries.\n"
            "Transcribe this dictionary page image into TEI Lex-0 XML format.\n"
            "Return only raw <entry> elements."
        )


# Global singleton
tei_prompt_builder = TeiPromptBuilder()
