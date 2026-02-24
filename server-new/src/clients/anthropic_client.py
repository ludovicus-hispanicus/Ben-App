import anthropic
import base64
import logging
from typing import Dict, Any
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


class AnthropicOcrClient(BaseOcrClient):
    def __init__(self, api_key: str, model: str = None):
        self.client = anthropic.Anthropic(api_key=api_key)
        # Use provided model or default to Claude Haiku 4.5 (fastest and most cost-effective)
        self.model_id = model if model else 'claude-haiku-4-5-20251001'
        logging.info(f"AnthropicOcrClient initialized with model: {self.model_id}")

    def ocr_image(self, image_base64: str, image_width: int, image_height: int, prompt: str = None) -> Dict[str, Any]:
        # Select prompt based on mode (default to dictionary for Akkadian texts)
        output_mode = prompt if prompt in PROMPTS else "dictionary"
        ocr_prompt = PROMPTS[output_mode]
        logging.info(f"Anthropic OCR using prompt mode: {output_mode}")

        try:
            # Create message with image
            message = self.client.messages.create(
                model=self.model_id,
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_base64,
                                },
                            },
                            {
                                "type": "text",
                                "text": ocr_prompt
                            }
                        ],
                    }
                ],
            )

            # Extract text from response
            response_text = message.content[0].text
            text_lines = [line.strip() for line in response_text.split('\n') if line.strip()]

            # Anthropic doesn't return bounding boxes, so create estimated full-width boxes
            dimensions = [
                Dimensions(x=0, y=i * (image_height // max(1, len(text_lines))),
                          width=image_width,
                          height=image_height // max(1, len(text_lines)))
                for i in range(len(text_lines))
            ]

            return {"lines": text_lines, "dimensions": dimensions}

        except Exception as e:
            logging.error(f"Anthropic OCR extraction failed: {e}")
            return {"lines": [], "dimensions": []}
