"""ComicForge AI Gradio application entry point."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)

# Keep the documented ``python app.py`` command working from a fresh checkout
# without requiring an editable package install.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from comicforge_ai.ui import create_demo

demo = create_demo()


if __name__ == "__main__":
    demo.launch(
        server_name=os.getenv("COMICFORGE_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.getenv("COMICFORGE_SERVER_PORT", "7860")),
    )
