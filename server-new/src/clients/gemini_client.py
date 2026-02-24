from google import genai
from google.genai import types
import base64
import logging
from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions

# Prompts for different output modes (matching ollama_ocr_service)
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

class GeminiOcrClient(BaseOcrClient):
    def __init__(self, api_key: str, model: str = None):
        # The new SDK uses a Client object
        self.client = genai.Client(api_key=api_key)
        # Use provided model or default to gemini-2.0-flash (free tier available)
        self.model_id = model if model else 'gemini-2.0-flash'
        logging.info(f"GeminiOcrClient initialized with model: {self.model_id}")

    def ocr_image(self, image_base64: str, image_width: int, image_height: int, prompt: str = None) -> dict:
        # Select prompt based on mode (default to dictionary for Akkadian texts)
        output_mode = prompt if prompt in PROMPTS else "dictionary"
        ocr_prompt = PROMPTS[output_mode]

        logging.info(f"Gemini OCR using prompt mode: {output_mode}")

        try:
            # Decode base64 to bytes
            image_bytes = base64.b64decode(image_base64)

            # New SDK structure for multimodal content
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[
                    ocr_prompt,
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type="image/png"
                    )
                ]
            )

            text_lines = [line.strip() for line in response.text.split('\n') if line.strip()]

            dimensions = [
                Dimensions(x=0, y=0, width=image_width, height=image_height // max(1, len(text_lines)))
                for _ in text_lines
            ]

            return {"lines": text_lines, "dimensions": dimensions}

        except Exception as e:
            logging.error(f"Gemini OCR extraction failed: {e}")
            return {"lines": [], "dimensions": []}
