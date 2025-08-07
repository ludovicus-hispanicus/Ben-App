from handlers.ai_handler import AIHandler
from handlers.new_texts_handler import NewTextsHandler
from handlers.texts_handler import TextsHandler
from handlers.users_handler import UsersHandler

global_texts_handler = TextsHandler()
global_ai_handler = AIHandler()
global_new_text_handler = NewTextsHandler()
global_users_handler = UsersHandler()
