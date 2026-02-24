from openai import OpenAI
from typing import Dict, Any, List
import logging
from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions

# Prompts for different output modes
PROMPTS = {
    "plain": "OCR this image. Output the text exactly as shown, line by line. Do not include any introduction or explanation.",
    "markdown": "OCR this image and output as markdown format. Preserve structure with headers, bold, italic as appropriate.",
    "dictionary": """Transcribe this Akkadian dictionary entry to markdown.

FORMATTING RULES (apply to ALL text):
1. **BOLD** → headword (first word, appears larger/darker)
2. *italic* → all Akkadian words (transliterated cuneiform)
3. UPPERCASE → Sumerian logograms (e.g., DINGIR, LÚ)
4. Keep line breaks as in original
5. Output ONLY the formatted text, no explanations

Return ONLY the transliterated text with markdown formatting.""",
}


class OpenAIOcrClient(BaseOcrClient):
    def __init__(self, api_key: str, model: str = None):
        self.client = OpenAI(api_key=api_key)
        # Use provided model or default to gpt-4o
        self.model_name = model if model else "gpt-4o"
        logging.info(f"OpenAIOcrClient initialized with model: {self.model_name}")

    def ocr_image(self, image_base64: str, image_width: int, image_height: int, prompt: str = None) -> Dict[str, Any]:
        # Select prompt based on mode (default to dictionary for Akkadian texts)
        output_mode = prompt if prompt in PROMPTS else "dictionary"
        ocr_prompt = PROMPTS[output_mode]
        logging.info(f"OpenAI OCR using prompt mode: {output_mode}")

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": ocr_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                }
                            },
                        ],
                    }
                ],
                max_tokens=2048,
            )

            content = response.choices[0].message.content
            text_lines = [line.strip() for line in content.split('\n') if line.strip()]

            # Dummy dimensions
            dimensions = [
                Dimensions(x=0, y=0, width=image_width, height=image_height // max(1, len(text_lines)))
                for _ in text_lines
            ]
            
            return {"lines": text_lines, "dimensions": dimensions}

        except Exception as e:
            logging.error(f"OpenAI OCR extraction failed: {e}")
            return {"lines": [], "dimensions": []}
