"""PyInstaller entry point for the CuReD backend server.

``cured-server --ketos <args>`` runs Kraken's ketos instead of the server: the
installed app has no Python of its own, so Kraken training (a subprocess) is
started through this executable.
"""
import multiprocessing
import os
import sys

# Ultralytics installs missing optional packages with pip when it imports them
# ("AutoUpdate"); the installed app has no pip, and BEn shouldn't change its environment.
os.environ.setdefault("YOLO_AUTOINSTALL", "False")

if __name__ == "__main__":
    # Training data loaders start worker processes; in the frozen executable
    # those re-run this file, and freeze_support() hands them their work.
    multiprocessing.freeze_support()

    if len(sys.argv) > 1 and sys.argv[1] == "--ketos":
        from services.ketos_wrapper import main as ketos_main
        sys.exit(ketos_main(sys.argv[2:]))

    # When running from PyInstaller bundle, set the working directory
    # to the executable's location so relative paths resolve correctly
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))

    import uvicorn
    from main import app

    port = int(os.environ.get("APP_PORT", 5001))
    uvicorn.run(app, host="0.0.0.0", port=port)
