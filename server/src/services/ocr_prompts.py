"""
Shared OCR prompt templates and output modes.
Used by Qwen LoRA inference and training services.
"""

import logging

# Plain text transcription (default)
PROMPT_PLAIN_TEXT = """OCR this image. Output the text exactly as shown."""

# Markdown output
PROMPT_MARKDOWN = """<|grounding|>Convert the document to markdown."""

# TEI Lex-0 XML output for dictionary entries
def _load_tei_lex0_prompt():
    try:
        from services.tei_prompt_builder import tei_prompt_builder
        return tei_prompt_builder.build_system_prompt()
    except Exception as e:
        logging.warning(f"Could not load TEI Lex-0 system prompt: {e}")
        return "Transcribe this dictionary page into TEI Lex-0 XML. Return only raw <entry> elements."

PROMPT_TEI_LEX0 = _load_tei_lex0_prompt()

# TEI for cuneiform texts (inscriptions, tablets)
PROMPT_TEI_EPIDOC = """You are an expert in digitizing cuneiform texts.
Transcribe this cuneiform text image into TEI EpiDoc XML format.

Use this structure:
<div type="edition" xml:lang="akk">
  <ab>
    <lb n="1"/>LINE_1_TRANSLITERATION
    <lb n="2"/>LINE_2_TRANSLITERATION
  </ab>
</div>

Rules:
1. Each line gets an <lb n="N"/> line break element
2. Preserve all special characters: š, ṣ, ṭ, ḫ, ā, ē, ī, ū
3. Mark damaged/unclear readings with <unclear>text</unclear>
4. Mark gaps with <gap reason="lost" extent="unknown"/>
5. Use <supplied reason="lost">text</supplied> for restored text

Output valid TEI EpiDoc XML:"""

# Available output modes
OUTPUT_MODES = {
    "plain": PROMPT_PLAIN_TEXT,
    "markdown": PROMPT_MARKDOWN,
    "tei_lex0": PROMPT_TEI_LEX0,
    "tei_epidoc": PROMPT_TEI_EPIDOC,
}
