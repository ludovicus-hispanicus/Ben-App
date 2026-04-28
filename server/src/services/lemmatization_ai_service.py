"""
Lemmatization AI Service

Uses Gemini to provide contextual lemma suggestions for ATF transliterations.
Sends the full text with relevant dictionary entries to disambiguate homonyms
and handle unknown forms.
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional, Any

from entities.lemmatization import (
    TextLemmatization, LineLemmatization, LemmaAssignment, TokenizedText
)
from services.atf_tokenizer import AtfTokenizer
from services.dictionary_service import DictionaryService

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert Assyriologist specializing in Akkadian and Sumerian cuneiform texts.
Your task is to assign lemma IDs from the eBL (Electronic Babylonian Literature) dictionary to each word token
in an ATF (Assyriological Text Format) transliteration.

Rules:
1. For each text line, output the tokens with their assigned lemma IDs.
2. Use the dictionary entries provided to match tokens to their correct lemma.
3. For ambiguous forms (multiple possible lemmas), use the surrounding textual context to disambiguate.
4. For tokens with no dictionary match, use your knowledge of Akkadian/Sumerian to suggest the most likely lemma ID
   in the format "lemma HOMONYM" (e.g., "epēšu I", "šarru I").
5. Determinatives ({d}, {m}, {f}, {ki}, etc.) should NOT be lemmatized — skip them.
6. Numbers, broken signs (x, X, ...), and structure/state lines should NOT be lemmatized.
7. If you cannot determine a lemma, use an empty array [].

Output ONLY valid JSON with no other text. The format is:
{
  "lines": [
    {
      "line_number": "1.",
      "tokens": [
        {"value": "a-na", "unique_lemma": ["ana I"]},
        {"value": "LUGAL", "unique_lemma": ["šarru I"]}
      ]
    }
  ]
}"""


class LemmatizationAiService:
    """AI-powered lemmatization using Gemini."""

    def __init__(self):
        self._client = None
        self._model_id = 'gemini-2.5-flash'

    def _get_client(self):
        """Lazy-initialize the Gemini client."""
        if self._client is None:
            try:
                from google import genai
                api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
                if not api_key:
                    raise ValueError("No Gemini API key found (GEMINI_API_KEY or GOOGLE_API_KEY)")
                self._client = genai.Client(api_key=api_key)
            except ImportError:
                raise ImportError("google-genai package not installed")
        return self._client

    async def suggest(
        self,
        atf_text: str,
        production_id: int,
        tokenizer: AtfTokenizer,
        dictionary: DictionaryService
    ) -> TextLemmatization:
        """Generate AI lemma suggestions for an ATF text."""

        # Step 1: Tokenize
        tokenized = tokenizer.tokenize(atf_text)

        # Step 2: Collect dictionary context for ambiguous/unknown tokens
        dict_context = self._build_dictionary_context(tokenized, dictionary)

        # Step 3: Build the prompt
        prompt = self._build_prompt(atf_text, dict_context)

        # Step 4: Call Gemini
        response_text = await self._call_gemini(prompt)

        # Step 5: Parse response into TextLemmatization
        result = self._parse_response(response_text, tokenized, production_id)
        result.ai_suggested = True

        return result

    def _build_dictionary_context(
        self, tokenized: TokenizedText, dictionary: DictionaryService
    ) -> str:
        """Build dictionary context string for ambiguous/unknown tokens."""
        # Collect unique tokens that need context
        tokens_needing_context = {}
        for line in tokenized.lines:
            if line.line_type != "text":
                continue
            for token in line.tokens:
                if token.is_determinative or token.is_number:
                    continue
                cleaned = token.cleaned
                if cleaned in tokens_needing_context:
                    continue

                candidates = dictionary.lookup(cleaned)
                if len(candidates) == 0 or len(candidates) >= 2:
                    # Unknown or ambiguous — include context
                    entries = []
                    for cid in candidates:
                        entry = dictionary.get_word_entry(cid)
                        if entry:
                            entries.append(f"  - {entry.word_id}: {', '.join(entry.pos)} \"{entry.guide_word}\"")
                    tokens_needing_context[cleaned] = entries

        if not tokens_needing_context:
            return ""

        lines = ["Dictionary entries for ambiguous/unknown tokens:"]
        for form, entries in tokens_needing_context.items():
            lines.append(f"\n{form}:")
            if entries:
                lines.extend(entries)
            else:
                lines.append("  (no dictionary match — use your expertise)")

        return "\n".join(lines)

    def _build_prompt(self, atf_text: str, dict_context: str) -> str:
        """Build the full prompt for Gemini."""
        parts = [SYSTEM_PROMPT, "\n\n---\n\nATF Text:\n", atf_text]
        if dict_context:
            parts.extend(["\n\n---\n\n", dict_context])
        return "".join(parts)

    async def _call_gemini(self, prompt: str) -> str:
        """Call Gemini and return the response text."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        client = self._get_client()

        def _call():
            response = client.models.generate_content(
                model=self._model_id,
                contents=[prompt],
            )
            return response.text

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = await loop.run_in_executor(executor, _call)

        return result

    def _parse_response(
        self, response_text: str, tokenized: TokenizedText, production_id: int
    ) -> TextLemmatization:
        """Parse Gemini's JSON response into TextLemmatization."""
        # Extract JSON from response (may be wrapped in markdown code blocks)
        json_str = response_text.strip()
        if json_str.startswith("```"):
            # Remove markdown code fences
            json_str = re.sub(r'^```(?:json)?\s*', '', json_str)
            json_str = re.sub(r'\s*```$', '', json_str)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}\nResponse: {response_text[:500]}")
            # Fall back to empty lemmatization
            return self._empty_lemmatization(tokenized, production_id)

        lines = []
        ai_lines = data.get("lines", [])

        # Map AI results back to tokenized lines
        ai_line_map = {}
        for ai_line in ai_lines:
            ln = ai_line.get("line_number", "")
            ai_line_map[ln] = ai_line.get("tokens", [])

        for tl in tokenized.lines:
            if tl.line_type != "text":
                continue

            ai_tokens = ai_line_map.get(tl.line_number, [])
            ai_token_map = {t.get("value", ""): t.get("unique_lemma", []) for t in ai_tokens}

            assignments = []
            for token in tl.tokens:
                if token.is_determinative or token.is_number:
                    assignments.append(LemmaAssignment(value=token.raw, unique_lemma=[]))
                    continue

                # Try to match by raw value
                lemma = ai_token_map.get(token.raw, [])
                if not lemma:
                    # Try cleaned value
                    lemma = ai_token_map.get(token.cleaned, [])
                assignments.append(LemmaAssignment(value=token.raw, unique_lemma=lemma))

            lines.append(LineLemmatization(
                line_number=tl.line_number,
                tokens=assignments
            ))

        return TextLemmatization(
            production_id=production_id,
            content_hash=tokenized.content_hash,
            lines=lines
        )

    def _empty_lemmatization(
        self, tokenized: TokenizedText, production_id: int
    ) -> TextLemmatization:
        """Create empty lemmatization from tokenized text."""
        lines = []
        for tl in tokenized.lines:
            if tl.line_type != "text":
                continue
            assignments = [
                LemmaAssignment(value=token.raw, unique_lemma=[])
                for token in tl.tokens
            ]
            lines.append(LineLemmatization(
                line_number=tl.line_number,
                tokens=assignments
            ))
        return TextLemmatization(
            production_id=production_id,
            content_hash=tokenized.content_hash,
            lines=lines
        )
