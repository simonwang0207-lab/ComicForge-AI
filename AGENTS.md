# AGENTS.md

## Project scope

ComicForge AI is a Python 3.11 comic-generation platform. Keep text generation, image generation, page composition, application orchestration, and UI code separated so providers can be replaced independently.

## Architecture rules

- Keep application code under `src/comicforge_ai/`.
- Use Pydantic models from `schemas.py` at component boundaries.
- All text models must implement `TextModelProvider` from `models/base.py`.
- Register selectable providers through `TextModelRegistry`; do not branch on provider IDs in UI or the main generation flow.
- All image models must implement `ImageProvider` from `models/image_base.py`.
- Register selectable image providers through `ImageProviderRegistry`; text and image providers must remain independently selectable.
- Image Provider boundaries use `ImageGenerationRequest`, `ImageGenerationResult`, and `ImageProviderCapabilities`; never silently ignore an unsupported request parameter.
- Do not hard-code image Provider/model choices in Gradio. Derive controls from registry model definitions and capabilities.
- Provider-specific URLs, payloads, credentials, and HTTP behavior belong only in provider modules.
- Gradio callbacks may collect inputs, call service methods, and format outputs; they must not contain provider or generation business logic.
- Prompt text belongs under `prompts/`, not in UI, service, or HTTP adapters.
- Parse model JSON only with safe JSON tooling and Pydantic. Never use `eval` or execute model output.
- Remote failures may fall back to Mock only when configured, and every fallback must expose its reason and actual provider to the caller.
- Do not impose four-panel, eight-panel, or UI-specific limits in core schemas or services.
- Preserve backward compatibility for the day-one Mock image and PNG pipeline while it remains in use.
- Pass only one panel's visual prompt to an image provider. Add dialogue, narration, numbering, and layout locally.
- Never ask an image Provider to draw comic text or ready-made bubbles. Plan negative space before generation, then render structured text locally.
- Paid image generation must remain separable from script generation/review so users can confirm edits first.
- Preserve legacy dialogue/narration migration and default missing content language to `zh-CN`.
- Persist generated image provenance and relative paths in `project.json`, never credentials.

## Security and configuration

- Read provider settings from environment variables or explicit constructor arguments.
- Never hard-code, print, log, test with, document, or commit a real API key.
- Keep `.env` ignored. `.env.example` may contain names, blank values, localhost URLs, and safe placeholders only.
- Do not add or download large model weights as part of project setup or tests.
- Do not contact real external APIs in automated tests.
- Inject a fake HTTP transport in provider tests.
- Remote image tests must use fake JSON/download transports and in-memory image bytes.
- Avoid including raw provider response bodies in HTTP errors because they may contain sensitive information.
- Keep connection and generation/read timeouts separate; local model generation must not inherit a short status-check timeout.
- Preserve the original exception and elapsed time on request errors, but never attach credentials, request headers, or full response bodies.
- For Ollama thinking models, send `think=false` as a top-level API field and keep `/no_think` as the compatibility fallback.
- For remote images, save URL or base64 results locally and validate them with Pillow before composition.
- A failed image panel may fall back independently only when configured, and the panel record must expose the reason.
- Retry only transient image failures (429, 5xx, network, timeout) with bounded backoff; asynchronous Providers must have a maximum polling deadline.
- Never store full image base64 payloads in `project.json`; downloaded content must enforce Content-Type, byte, and timeout limits.

## Development rules

- Generated artifacts belong in `outputs/` and must not be committed.
- Add or update pytest tests whenever behavior changes.
- Keep Mock providers deterministic so offline tests and demonstrations remain reliable.
- Preserve Chinese UI labels and understandable validation/error messages.
- Prefer the Python standard library over heavyweight provider frameworks when the behavior is simple.
- Do not commit or push unless the user explicitly asks.

## Verification

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall -q app.py src tests
.\.venv\Scripts\python.exe -c "import app; assert app.demo"
```

When possible, launch the app locally and verify an HTTP 200 response without invoking a real text provider.
