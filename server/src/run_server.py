"""PyInstaller entry point for the CuReD backend server."""
import os
import sys
import uvicorn

# When running from PyInstaller bundle, set the working directory
# to the executable's location so relative paths resolve correctly
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

from main import app

if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", 5001))
    uvicorn.run(app, host="0.0.0.0", port=port)
