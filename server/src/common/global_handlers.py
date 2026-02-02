from handlers.new_texts_handler import NewTextsHandler
from handlers.texts_handler import TextsHandler
from handlers.users_handler import UsersHandler
import logging

# AIHandler requires OCR module which may not be available
try:
    from handlers.ai_handler import AIHandler
    global_ai_handler = AIHandler()
except ImportError as e:
    logging.warning(f"AIHandler not available: {e}. Some features will be disabled.")
    global_ai_handler = None

global_texts_handler = TextsHandler()
global_new_text_handler = NewTextsHandler()
global_users_handler = UsersHandler()
