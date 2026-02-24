"""Test Qwen3-VL with better prompts for consistent markdown formatting"""
import ollama
import base64

image_path = r"c:\Users\wende\Documents\GitHub\BEn-app\yolo_snippets\07_entry_1.00.png"

with open(image_path, "rb") as f:
    image_data = base64.b64encode(f.read()).decode()

# Different prompts to try
prompts = {
    "detailed": """This is a dictionary entry from AHw (Akkadisches Handwörterbuch).
OCR this image with careful attention to typography:
- The headword at the beginning is in BOLD - use **bold**
- Akkadian words and forms are in ITALIC - use *italic* for ALL of them
- German translations are in regular text
- Apply formatting consistently throughout the ENTIRE text, not just the first line.

Output the complete text with markdown formatting.""",

    "examples": """OCR this dictionary image. The text uses different fonts:
- Bold = headwords (main entry words) → use **word**
- Italic = Akkadian language words → use *word*
- Regular = German translations and references

Example: If you see "qablū(m)" in bold and "nārim" in italic, output:
**qablū(m)** ... *nārim* ...

Apply this formatting to ALL words throughout the text, not just the beginning.""",

    "systematic": """Transcribe this Akkadian dictionary entry to markdown.

FORMATTING RULES (apply to ALL text):
1. **BOLD** → headword (first word, appears larger/darker)
2. *ITALIC* → ALL Akkadian words (they look slanted/cursive)
3. Regular → German words, abbreviations, references

IMPORTANT: Akkadian words appear throughout the entry (not just at start).
They include: nārim, bābu, šamû, ubānu, etc. Mark ALL italic text with *asterisks*.

Begin transcription:""",
}

for name, prompt in prompts.items():
    print(f"\n{'='*60}")
    print(f"PROMPT: {name}")
    print('='*60)

    try:
        response = ollama.chat(
            model='qwen3-vl:235b-cloud',
            messages=[{
                'role': 'user',
                'content': prompt,
                'images': [image_data]
            }]
        )

        result = response['message']['content']

        # Count formatting markers
        bold_count = result.count('**') // 2
        italic_count = result.count('*') - result.count('**') * 2
        italic_count = italic_count // 2 if italic_count > 0 else 0

        print(f"Bold instances: ~{bold_count}")
        print(f"Italic instances: ~{italic_count}")

        # Save output
        output_file = f"c:\\Users\\wende\\Documents\\GitHub\\BEn-app\\qwen3_prompt_{name}.md"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# Qwen3-VL - Prompt: {name}\n\n")
            f.write(f"## Prompt:\n```\n{prompt}\n```\n\n")
            f.write(f"## Output:\n\n{result}")

        print(f"Saved: {output_file}")

    except Exception as e:
        print(f"Error: {e}")

print("\n\nDone! Check the output files.")
