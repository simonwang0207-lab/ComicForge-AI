# AGENTS.md

## Project scope

ComicForge AI is a Python 3.11 comic-generation platform. Keep text generation,
image generation, page composition, and user-interface code separated so mock
implementations can later be replaced by real model adapters.

## Development rules

- Keep all application code under `src/comicforge_ai/`.
- Use Pydantic models from `schemas.py` at component boundaries.
- Model adapters must not directly depend on Gradio.
- The day-one demo must remain fully local and require no API key.
- Do not add or download large model weights.
- Generated artifacts belong in `outputs/` and must not be committed.
- Add or update pytest tests whenever behavior changes.
- Preserve Chinese UI labels and helpful validation messages.

## Verification

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -c "import app; assert app.demo"
```
