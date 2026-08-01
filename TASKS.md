# ComicForge AI Tasks

## Day 1 — Project skeleton and Mock Demo

- [x] Create a standard Python `src/` project structure
- [x] Define the initial Pydantic comic data models
- [x] Implement story and storyboard generation with `MockTextModel`
- [x] Implement Pillow placeholder panels with `MockImageModel`
- [x] Compose panels into a comic page
- [x] Add a Chinese Gradio interface
- [x] Preview and export PNG results
- [x] Add project documentation and baseline pytest coverage

## Stage 2 — Real text models and unified Provider architecture

- [x] Define a common `TextModelProvider` contract and friendly error types
- [x] Add provider IDs, display names, runtime types, model names, and status checks
- [x] Keep `MockTextModel` as the always-available offline provider
- [x] Add local Ollama HTTP provider
- [x] Disable Qwen3 thinking with `think=false` and `/no_think` compatibility fallback
- [x] Separate connection, status, and generation timeouts (300-second generation default)
- [x] Distinguish connection, HTTP, missing-model, and generation-timeout errors
- [x] Record provider request duration and original exceptions
- [x] Add generic OpenAI-compatible Chat Completions provider
- [x] Add environment-based provider registry and lookup
- [x] Separate comic-generation and JSON-repair prompts from providers
- [x] Extract plain or Markdown-fenced JSON without `eval`
- [x] Validate model output through expanded Pydantic schemas
- [x] Add one configurable JSON repair retry
- [x] Support arbitrary positive panel counts in schemas and service
- [x] Reserve page grouping through `ComicPage` and `page_number`
- [x] Add explicit Mock fallback with failure reason and provider provenance
- [x] Add model selection and availability checks to Gradio
- [x] Preserve Mock images, page composition, preview, and PNG export
- [x] Add fully mocked HTTP and regression tests
- [x] Verify real Ollama generation with local `qwen3:4b` and no Mock fallback
- [x] Update configuration and documentation

## Next — Stage 3 candidates

- [ ] Verify one chosen OpenAI-compatible service with a locally supplied credential
- [ ] Define a common image-model Provider interface
- [ ] Integrate the first opt-in real image provider
- [ ] Add image-provider error classification and explicit Mock fallback
- [ ] Add project JSON persistence and reload support
- [ ] Add per-panel editing and selective regeneration
- [ ] Add configurable page templates, speech bubbles, and multi-page export
- [ ] Add prompt/version metadata and generation cost or timing telemetry
