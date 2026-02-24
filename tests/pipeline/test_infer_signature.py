"""Check what parameters the infer method accepts."""
import sys
import os
import inspect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server", "src"))

from services import deepseek_ocr_service

# Load model first
if not deepseek_ocr_service.is_loaded():
    deepseek_ocr_service.load_model()

# Get the model
model = deepseek_ocr_service._model

# Print the infer method signature
print("infer() method signature:")
print(inspect.signature(model.infer))
print()

# Try to get the source if available
try:
    print("infer() source:")
    print(inspect.getsource(model.infer))
except:
    print("Source not available")
