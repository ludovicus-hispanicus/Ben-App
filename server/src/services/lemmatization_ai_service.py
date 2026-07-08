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


def _is_broken_placeholder(text: str) -> bool:
    """Detect broken-sign placeholder tokens — pure "x" stand-ins and bare
    ellipses — across every variant the tokenizer can produce ("x", "[x",
    "x]", "x...", "[...]", "...]", etc.).

    Strategy: strip brackets/ellipsis/parens, then strip x/X/dots/whitespace.
    If nothing meaningful is left, this is a placeholder we should never
    lemmatize. Mirrors the same-named TS helper in the lemmatization panel.
    """
    if not text:
        return True
    base = re.sub(r"[\[\]⌈⌉()<>°…]", "", text).strip()
    if not base:
        return True
    meaningful = re.sub(r"[xX.\s]", "", base)
    return len(meaningful) == 0

SYSTEM_PROMPT = """You are an expert Assyriologist specializing in Akkadian and Sumerian cuneiform texts.
Your task is to assign lemma IDs from the eBL (Electronic Babylonian Literature) dictionary to each word token
in an eBL-ATF transliteration. Use the eBL dictionary's lemma format throughout — e.g., "šarru I", "ana I",
"epēšu I" — with the Roman numeral homonym suffix.

You will receive (in this priority order):
1. HUMAN-CONFIRMED ASSIGNMENTS — lemmas the human user has already explicitly confirmed. These are
   ANCHORS: do not change them, do not propose alternatives. Their only role in your input is to
   help you stay consistent across the rest of the text (e.g., if the human confirmed "KA = pû I" on
   one line, prefer the same lemma for "KA" on other lines unless the context clearly differs).
2. UNCONFIRMED SUGGESTIONS — lemma hints already on the text from a previous run (ORACC import or
   prior AI pass) that the human has NOT yet confirmed. Treat them as a starting hypothesis: confirm
   them when they fit, override them only when the dictionary entries or the translation give clear
   evidence they are wrong. Never silently drop a prior unless you are replacing it.
3. DICTIONARY ENTRIES — the canonical eBL lemma candidates for ambiguous or unknown forms. Always pick
   from these when one fits.
4. TRANSLATION — the human-edited translation of the same text. Use it to disambiguate homonyms
   ("šarru" the king vs another root), to confirm verb tenses, and to identify which sense of a noun
   is meant. The translation is the strongest signal you have for context-dependent choices.

TRANSLITERATION QUALITY: the transliteration may contain OCR errors, broken signs (rendered as "x"),
missing diacritics, or damaged-text brackets ([ ], ⌈ ⌉, partial words like "GAR-i["). Be flexible:
recognize close variants, give weight to the dictionary form even when the transliteration is borderline,
and leave clearly-broken tokens unassigned rather than guess from corrupted input.

Rules:
1. For each text line, output the tokens with their assigned lemma IDs.
2. Use the dictionary entries provided to match tokens to their correct lemma.
3. For ambiguous forms (multiple possible lemmas), use the translation and surrounding text to disambiguate.
4. For tokens with no dictionary match, use your knowledge of Akkadian/Sumerian to suggest the most likely lemma ID
   in the format "lemma HOMONYM" (e.g., "epēšu I", "šarru I").
5. Determinatives ({d}, {m}, {f}, {ki}, etc.) should NOT be lemmatized — skip them.
6. Numbers, broken signs (x, X, ...), and structure/state lines should NOT be lemmatized.
7. If you cannot determine a lemma, use an empty array [].

LINE IDENTITY — CRITICAL:
Every text line in the input is prefixed with a tag of the form [L1], [L2], [L3], …
Use that exact tag (without the brackets) as the "line_number" field in your output.
This is the ONLY reliable way for us to map your output back to the input.
Do NOT invent your own numbering. Do NOT use "1.", "1'.", or content-based labels —
use the literal tag we prefixed.

Output ONLY valid JSON with no other text. The format is:
{
  "lines": [
    {
      "line_number": "L1",
      "tokens": [
        {"value": "a-na", "unique_lemma": ["ana I"]},
        {"value": "LUGAL", "unique_lemma": ["šarru I"]}
      ]
    },
    {
      "line_number": "L2",
      "tokens": [
        {"value": "[DIŠ", "unique_lemma": ["šumma I"]}
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
        dictionary: DictionaryService,
        translation_content: str = "",
        existing_lemmatization: Optional[TextLemmatization] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        extra_instruction: Optional[str] = None,
    ) -> TextLemmatization:
        """Generate AI lemma suggestions for an ATF text.

        New (vs the original Gemini-only version):
          - `translation_content`: human-edited translation, passed to the model
            so it can disambiguate homonyms by sense.
          - `existing_lemmatization`: prior suggestions (e.g. from an ORACC
            import) — passed verbatim as a starting hypothesis. The model is
            instructed to confirm them when correct and override only on
            evidence.
          - `provider`/`model`/`api_key`: reuse the per-word dispatcher so the
            user picks the LLM (Gemini, Claude, OpenAI, Grok) with the same
            keys they already saved for OCR.

        Every returned assignment is marked is_suggestion=True with
        suggestion_source="ai" so the panel can render them in a distinct
        colour and the user can accept/reject like ORACC imports.
        """
        tokenized = tokenizer.tokenize(atf_text)

        # Inject a stable [L<n>] tag on every text line so the model has an
        # unambiguous handle to reference each line in its JSON output, even
        # when the ATF itself doesn't use line numbers (e.g., raw OCR'd text
        # like "[DIŠ KA DUG₃.GA …]" with no "1." prefix). The tokenizer's
        # tl.line_number is often empty in that case, so we can't rely on it
        # for matching.
        annotated_text, tag_for_tl = self._annotate_with_line_tags(atf_text, tokenized)

        dict_context = self._build_dictionary_context(tokenized, dictionary)
        prior_context = self._build_prior_suggestions_context(existing_lemmatization, tokenized)
        translation_context = self._build_translation_context(translation_content)

        prompt = self._build_prompt(
            annotated_text, dict_context,
            prior_context=prior_context,
            translation_context=translation_context,
            extra_instruction=(extra_instruction or "").strip(),
        )

        # Budget max_tokens for the response. JSON output per token is
        # roughly 30-45 chars ≈ 10-15 tokens. We over-budget conservatively
        # because Claude truncates fatally at max_tokens with no recovery.
        n_text_tokens = sum(
            len(tl.tokens) for tl in tokenized.lines if tl.line_type == "text"
        )
        budgeted_max = max(8192, n_text_tokens * 30 + 2048)
        logger.info(
            f"AI bulk lemmatization: production_id={production_id} "
            f"text_lines={len(tag_for_tl)} tokens≈{n_text_tokens} "
            f"max_tokens={budgeted_max} provider={provider!r} model={model!r}"
        )

        response_text = await self._call_provider(
            prompt, provider=provider, model=model, api_key=api_key,
            max_tokens=budgeted_max,
        )

        result = self._parse_response(
            response_text, tokenized, production_id, tag_for_tl=tag_for_tl,
        )
        result.ai_suggested = True

        # Tag every non-empty assignment as an AI suggestion so the UI can
        # render it in the AI color and the user can accept/reject.
        for line in result.lines:
            for tok in line.tokens:
                if tok.unique_lemma:
                    tok.is_suggestion = True
                    tok.suggestion_source = "ai"

        return result

    async def _call_provider(
        self,
        prompt: str,
        provider: Optional[str],
        model: Optional[str],
        api_key: Optional[str],
        max_tokens: Optional[int] = None,
    ) -> str:
        """Dispatch to the requested LLM backend. Defaults to Gemini when
        provider is None — preserves backward compatibility with the original
        suggest() signature.

        `max_tokens` is forwarded to providers that require an explicit cap
        (Claude is fatal-truncated at the default 2048 otherwise — see the
        bulk-lemma cap below). Gemini has no per-call cap by default and the
        OpenAI-compat models pick a sensible default when unset."""
        p = (provider or "gemini").lower()
        if p in ("gemini", "gemini_vision"):
            return await self._call_gemini(prompt, model=model, api_key=api_key)
        if p in ("anthropic", "claude", "claude_vision"):
            # Claude needs an explicit max_tokens. 2048 was the per-word default
            # — far too small for whole-text lemmatization. Default to 8192 and
            # let the bulk path override upward.
            return await self._call_claude(prompt, model=model, api_key=api_key,
                                           max_tokens=max_tokens or 8192)
        if p in ("openai", "gpt", "gpt4_vision"):
            return await self._call_openai(prompt, model=model, api_key=api_key,
                                           max_tokens=max_tokens)
        if p in ("grok", "xai", "grok_xai"):
            return await self._call_grok(prompt, model=model, api_key=api_key,
                                         max_tokens=max_tokens)
        raise ValueError(f"Unknown AI provider: {provider!r}")

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

    def _build_prior_suggestions_context(
        self,
        existing: Optional[TextLemmatization],
        tokenized: TokenizedText,
    ) -> str:
        """Surface prior lemma data to the model, split into two sections:
          - HUMAN-CONFIRMED ASSIGNMENTS: anchors the model must not change
          - UNCONFIRMED SUGGESTIONS: ORACC priors or earlier AI suggestions
            the model may confirm or correct

        Lines are addressed by their tokenizer line_number so the model can
        correlate with the input. Tokens without any prior signal are omitted
        to keep the prompt focused.
        """
        if not existing or not existing.lines:
            return ""

        # Map ATF line_number -> tokenized line (so we can include the raw token
        # for context when emitting a prior).
        tl_by_number: Dict[str, Any] = {
            tl.line_number: tl for tl in tokenized.lines if tl.line_type == "text"
        }

        def _format_assignment(assignment: Any) -> Optional[str]:
            """Build the entry bits for one token. Returns None if there's no
            useful prior signal to surface."""
            has_prior_lemma = bool(assignment.unique_lemma)
            has_oracc_hint = bool(
                assignment.oracc_guideword
                or assignment.oracc_citation
                or assignment.oracc_pos
            )
            if not (has_prior_lemma or has_oracc_hint):
                return None
            bits: List[str] = []
            if has_prior_lemma:
                bits.append(f"lemma={', '.join(assignment.unique_lemma)}")
            if assignment.oracc_citation:
                bits.append(f'citation="{assignment.oracc_citation}"')
            if assignment.oracc_guideword:
                bits.append(f'gloss="{assignment.oracc_guideword}"')
            if assignment.oracc_pos:
                bits.append(f"pos={assignment.oracc_pos}")
            return f"  - {assignment.value}: " + "; ".join(bits)

        confirmed_blocks: List[str] = []
        unconfirmed_blocks: List[str] = []
        for lem_line in existing.lines:
            tl = tl_by_number.get(lem_line.line_number)
            if tl is None:
                continue
            confirmed_for_line: List[str] = []
            unconfirmed_for_line: List[str] = []
            for assignment in lem_line.tokens:
                entry = _format_assignment(assignment)
                if entry is None:
                    continue
                # An assignment counts as "human-confirmed" when it has an
                # actual lemma AND the suggestion flag is off (the user
                # explicitly accepted or assigned it). Empty-lemma rows with
                # only ORACC metadata stay in the unconfirmed bucket.
                is_confirmed = (
                    bool(assignment.unique_lemma)
                    and not assignment.is_suggestion
                )
                if is_confirmed:
                    confirmed_for_line.append(entry)
                else:
                    unconfirmed_for_line.append(entry)
            line_label = f"Line {lem_line.line_number}:"
            if confirmed_for_line:
                confirmed_blocks.append(line_label)
                confirmed_blocks.extend(confirmed_for_line)
            if unconfirmed_for_line:
                unconfirmed_blocks.append(line_label)
                unconfirmed_blocks.extend(unconfirmed_for_line)

        sections: List[str] = []
        if confirmed_blocks:
            sections.append(
                "HUMAN-CONFIRMED ASSIGNMENTS (anchors — do not change, use as consistency cues):\n"
                + "\n".join(confirmed_blocks)
            )
        if unconfirmed_blocks:
            sections.append(
                "UNCONFIRMED SUGGESTIONS (starting hypothesis — confirm or correct):\n"
                + "\n".join(unconfirmed_blocks)
            )
        return "\n\n".join(sections)

    def _build_translation_context(self, translation_content: str) -> str:
        """Pass the human translation as disambiguation context. We send the
        full block — the model can correlate by line number where the
        translation uses the same numbering as the ATF, and otherwise treat
        it as ambient sense context."""
        if not translation_content or not translation_content.strip():
            return ""
        return "Translation (use to disambiguate homonyms and verb senses):\n" + translation_content.strip()

    def _build_prompt(
        self,
        atf_text: str,
        dict_context: str,
        prior_context: str = "",
        translation_context: str = "",
        extra_instruction: str = "",
    ) -> str:
        """Build the full prompt. Sections appear in the same priority order
        the system prompt declares: priors → dictionary → translation. The
        user's editable instruction (if any) is appended last so it can
        steer behaviour without overriding the structural rules above."""
        parts: List[str] = [SYSTEM_PROMPT, "\n\n---\n\nATF Text:\n", atf_text]
        if prior_context:
            parts.extend(["\n\n---\n\n", prior_context])
        if dict_context:
            parts.extend(["\n\n---\n\n", dict_context])
        if translation_context:
            parts.extend(["\n\n---\n\n", translation_context])
        if extra_instruction:
            parts.extend([
                "\n\n---\n\nUser instruction (apply within the rules above):\n",
                extra_instruction,
            ])
        return "".join(parts)

    async def ask_about_word(
        self,
        prompt: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> str:
        """Send the user's pre-composed prompt to the selected LLM backend
        and return the freeform response. Used by the per-word "Ask AI" UI
        — the prompt is already context-rich (sentence + translation +
        question) and the response is shown to the user as informational
        text. `provider` selects the backend ("gemini", "anthropic"/"claude",
        or "openai"); `model` overrides the default model id; `api_key`
        falls back to the matching environment variable when omitted."""
        p = (provider or 'gemini').lower()
        if p in ('gemini', 'gemini_vision'):
            return await self._call_gemini(prompt, model=model, api_key=api_key)
        if p in ('anthropic', 'claude', 'claude_vision'):
            return await self._call_claude(prompt, model=model, api_key=api_key)
        if p in ('openai', 'gpt', 'gpt4_vision'):
            return await self._call_openai(prompt, model=model, api_key=api_key)
        if p in ('grok', 'xai', 'grok_xai'):
            return await self._call_grok(prompt, model=model, api_key=api_key)
        raise ValueError(f"Unknown AI provider: {provider!r}")

    # ── Provider dispatchers ────────────────────────────────────────────

    async def _call_gemini(self, prompt: str, model: Optional[str] = None, api_key: Optional[str] = None) -> str:
        """Call Gemini and return the response text."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        try:
            from google import genai
        except ImportError:
            raise ImportError("google-genai package not installed")

        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ValueError("No Gemini API key found (GEMINI_API_KEY or GOOGLE_API_KEY)")
        client = genai.Client(api_key=key)
        chosen_model = model or self._model_id

        def _call():
            response = client.models.generate_content(
                model=chosen_model,
                contents=[prompt],
            )
            return response.text

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = await loop.run_in_executor(executor, _call)
        return result

    async def _call_claude(self, prompt: str, model: Optional[str] = None, api_key: Optional[str] = None, max_tokens: int = 2048) -> str:
        """Call Anthropic Claude and return the response text."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package not installed")

        key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
        if not key:
            raise ValueError("No Anthropic API key found (ANTHROPIC_API_KEY)")
        client = anthropic.Anthropic(api_key=key)
        chosen_model = model or "claude-haiku-4-5-20251001"

        def _call():
            response = client.messages.create(
                model=chosen_model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            # response.content is a list of content blocks; concatenate text blocks
            return "".join(getattr(b, "text", "") for b in response.content)

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = await loop.run_in_executor(executor, _call)
        return result

    async def _call_openai(self, prompt: str, model: Optional[str] = None, api_key: Optional[str] = None, max_tokens: Optional[int] = None) -> str:
        """Call OpenAI and return the response text."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package not installed")

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("No OpenAI API key found (OPENAI_API_KEY)")
        client = OpenAI(api_key=key)
        chosen_model = model or "gpt-4o-mini"

        def _call():
            kwargs = {"model": chosen_model, "messages": [{"role": "user", "content": prompt}]}
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = await loop.run_in_executor(executor, _call)
        return result

    async def _call_grok(self, prompt: str, model: Optional[str] = None, api_key: Optional[str] = None, max_tokens: Optional[int] = None) -> str:
        """Call xAI Grok via its OpenAI-compatible endpoint at api.x.ai/v1.
        We reuse the `openai` SDK with a custom base_url — no extra dependency."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package not installed (used for xAI's OpenAI-compatible endpoint)")

        key = api_key or os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY")
        if not key:
            raise ValueError("No xAI API key found (XAI_API_KEY or GROK_API_KEY)")
        client = OpenAI(api_key=key, base_url="https://api.x.ai/v1")
        chosen_model = model or "grok-4-1-fast-non-reasoning"

        def _call():
            kwargs = {"model": chosen_model, "messages": [{"role": "user", "content": prompt}]}
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = await loop.run_in_executor(executor, _call)
        return result

    def _annotate_with_line_tags(
        self, atf_text: str, tokenized: TokenizedText
    ) -> tuple[str, Dict[str, Any]]:
        """Prefix every text line with [L<n>] so the model can address each
        line by an unambiguous tag in its JSON output. Returns the annotated
        text plus a `tag_for_tl` dict mapping the tag back to the tokenized
        line — used by the parser to resolve AI line_numbers to tl objects.

        Non-text lines (structure markers, comments) are passed through
        unchanged because we don't ask the model to lemmatize them.
        """
        # Build by walking the tokenized lines so the tag aligns 1:1 with
        # the lines the parser later iterates over.
        tag_for_tl: Dict[str, Any] = {}
        counter = 0
        # Build the annotated text by index — tl.atf_index is the 0-based
        # position of the line in the original ATF.
        atf_lines = atf_text.split("\n")
        annotated_lines = list(atf_lines)  # mutable copy
        for tl in tokenized.lines:
            if tl.line_type != "text":
                continue
            counter += 1
            tag = f"L{counter}"
            tag_for_tl[tag] = tl
            if 0 <= tl.atf_index < len(annotated_lines):
                # Re-prefix the existing line so any structure (indentation,
                # numbering already present) is preserved after the tag.
                annotated_lines[tl.atf_index] = f"[{tag}] {annotated_lines[tl.atf_index]}"
        return "\n".join(annotated_lines), tag_for_tl

    def _extract_json_block(self, response_text: str) -> str:
        """Strip markdown fences and trim to the JSON object boundaries."""
        s = response_text.strip()
        if s.startswith("```"):
            s = re.sub(r'^```(?:json)?\s*', '', s)
            s = re.sub(r'\s*```\s*$', '', s)
        # If the model added preamble before the JSON, grab from the first '{'.
        first = s.find("{")
        if first > 0:
            s = s[first:]
        return s

    def _repair_truncated_json(self, json_str: str) -> Optional[str]:
        """Try to salvage a JSON document that was cut off mid-output by a
        max_tokens limit. Walks the string maintaining a stack of open
        '{'/'[' brackets, and on each fully-closed inner element records a
        "safe end" index. After scanning, we truncate at the last safe end
        and close any still-open brackets in reverse-stack order so the
        result is well-formed."""
        stack: List[str] = []   # 'O' for object, 'A' for array
        in_string = False
        escape = False
        # Snapshot of the stack at the moment we last saw a fully-closed
        # element inside an array (token closing inside tokens[] OR line
        # closing inside lines[]). Allows us to know what to close.
        last_safe_end = -1
        last_safe_stack: List[str] = []
        for i, ch in enumerate(json_str):
            if escape:
                escape = False
                continue
            if in_string:
                if ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                stack.append("O")
            elif ch == "[":
                stack.append("A")
            elif ch == "}":
                if stack and stack[-1] == "O":
                    stack.pop()
                # A safe checkpoint is right after closing a complete inner
                # object that lives inside an array (so we can chop the
                # trailing comma + partial element without breaking the
                # surrounding structure).
                if stack and stack[-1] == "A":
                    last_safe_end = i
                    last_safe_stack = list(stack)
            elif ch == "]":
                if stack and stack[-1] == "A":
                    stack.pop()
                if stack and stack[-1] == "A":
                    last_safe_end = i
                    last_safe_stack = list(stack)
        if last_safe_end < 0:
            return None
        prefix = json_str[: last_safe_end + 1]
        # Close in reverse stack order: each 'A' → ']', each 'O' → '}'.
        closing = "".join("]" if k == "A" else "}" for k in reversed(last_safe_stack))
        return prefix + closing

    def _parse_response(
        self,
        response_text: str,
        tokenized: TokenizedText,
        production_id: int,
        tag_for_tl: Optional[Dict[str, Any]] = None,
    ) -> TextLemmatization:
        """Parse the AI's JSON response into a TextLemmatization.

        Matching strategy for each tokenized text line:
          1. Look up by [L<n>] tag if the model used the tags we injected
          2. Look up by the tokenizer's line_number (if non-empty)
          3. Fall back to positional matching — the i-th AI line goes to the
             i-th tokenized text line

        On JSON parse failure we first try to repair a truncated response;
        only if repair also fails do we raise a RuntimeError. Callers must
        NOT save the result over the user's existing lemmatization on raise.
        """
        json_str = self._extract_json_block(response_text)
        data: Optional[Dict[str, Any]] = None
        repair_used = False
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            repaired = self._repair_truncated_json(json_str)
            if repaired:
                try:
                    data = json.loads(repaired)
                    repair_used = True
                    logger.warning(
                        f"AI response JSON was truncated ({e}); "
                        f"recovered {len(repaired)} chars with "
                        f"{len(data.get('lines', []))} lines parseable"
                    )
                except json.JSONDecodeError as e2:
                    logger.error(
                        f"AI response JSON truncated AND repair failed: "
                        f"orig={e}, after_repair={e2}\n"
                        f"Response preview: {response_text[:500]}"
                    )
            if data is None:
                # Hard failure — surface to caller so the route returns an
                # error and the user's existing lemmatization stays intact.
                preview = response_text[:300] + ("…" if len(response_text) > 300 else "")
                raise RuntimeError(
                    f"AI response was not valid JSON and could not be repaired. "
                    f"This usually means the model's output was truncated by its "
                    f"token limit. Try a model with a larger context or a shorter "
                    f"text. Response preview: {preview}"
                )

        ai_lines = data.get("lines", [])
        if not isinstance(ai_lines, list) or not ai_lines:
            raise RuntimeError(
                "AI response had no 'lines' content — the model did not produce "
                "any lemma assignments."
            )

        # Build lookup maps from the AI output keyed by the line_number string
        # AND by 0-based position so we can fall through if the model used a
        # different identifier scheme than expected.
        ai_by_key: Dict[str, List[Dict[str, Any]]] = {}
        ai_by_pos: List[List[Dict[str, Any]]] = []
        for ai_line in ai_lines:
            ln = str(ai_line.get("line_number", "")).strip()
            toks = ai_line.get("tokens", [])
            if ln:
                ai_by_key[ln] = toks
            ai_by_pos.append(toks)

        # The parser walks tokenized.lines text lines in their original order;
        # `text_pos` is the 0-based position used for positional fallback.
        lines: List[LineLemmatization] = []
        text_pos = -1
        unmatched_lines: List[str] = []
        for tl in tokenized.lines:
            if tl.line_type != "text":
                continue
            text_pos += 1

            ai_tokens = None
            # 1. Tag-based (most reliable when we injected [L<n>] markers)
            if tag_for_tl:
                # Build reverse map once
                pass
            # The tag is just f"L{text_pos+1}" by construction in _annotate_with_line_tags.
            tag = f"L{text_pos + 1}"
            if tag in ai_by_key:
                ai_tokens = ai_by_key[tag]
            # 2. Original line_number on the tokenized line
            if ai_tokens is None and tl.line_number and tl.line_number in ai_by_key:
                ai_tokens = ai_by_key[tl.line_number]
            # 2b. Also try stripped trailing period: AtfTokenizer often emits "1.",
            #     model may emit "1" — and vice versa.
            if ai_tokens is None and tl.line_number:
                alt = tl.line_number.rstrip(".")
                if alt in ai_by_key:
                    ai_tokens = ai_by_key[alt]
                elif (alt + ".") in ai_by_key:
                    ai_tokens = ai_by_key[alt + "."]
            # 3. Positional fallback
            if ai_tokens is None and text_pos < len(ai_by_pos):
                ai_tokens = ai_by_pos[text_pos]
            if ai_tokens is None:
                ai_tokens = []
                unmatched_lines.append(tl.line_number or tag)

            # Token-value map for fast lookup, plus parallel positional access
            # for tokens the model rewrote slightly (e.g., dropped a flag).
            token_values: List[Tuple[str, List[str]]] = [
                (str(t.get("value", "")), t.get("unique_lemma", []) or [])
                for t in ai_tokens if isinstance(t, dict)
            ]
            ai_value_map = {v: lem for v, lem in token_values if v}

            assignments: List[LemmaAssignment] = []
            for ti, token in enumerate(tl.tokens):
                # Never persist a lemma for tokens that aren't lemmatizable —
                # determinatives, numbers, and pure "x"/"..." broken-sign
                # placeholders. The AI is told not to assign these but may
                # do so anyway; drop the assignment server-side either way.
                if (
                    token.is_determinative
                    or token.is_number
                    or _is_broken_placeholder(token.cleaned)
                    or _is_broken_placeholder(token.raw)
                ):
                    assignments.append(LemmaAssignment(value=token.raw, unique_lemma=[]))
                    continue
                lemma: List[str] = []
                if token.raw and token.raw in ai_value_map:
                    lemma = ai_value_map[token.raw]
                elif token.cleaned and token.cleaned in ai_value_map:
                    lemma = ai_value_map[token.cleaned]
                elif ti < len(token_values):
                    # Positional fallback within the line — only trust it when
                    # the surrounding values look roughly aligned (same length).
                    if len(token_values) == len(tl.tokens):
                        lemma = token_values[ti][1]
                assignments.append(LemmaAssignment(value=token.raw, unique_lemma=lemma))

            lines.append(LineLemmatization(
                line_number=tl.line_number,
                tokens=assignments
            ))

        if unmatched_lines:
            logger.warning(
                f"AI bulk lemmatization: {len(unmatched_lines)} lines had no "
                f"matching AI output (first few: {unmatched_lines[:5]}); "
                f"those tokens will be unassigned"
            )

        if repair_used:
            logger.info("AI bulk lemmatization: salvaged partial result from truncated JSON")

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
