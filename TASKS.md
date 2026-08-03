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
- [x] Define a common image-model Provider interface and registry
- [x] Integrate a generic OpenAI-compatible Images API provider
- [x] Support URL and `b64_json` image responses with local PNG persistence
- [x] Keep Mock Image as the offline provider and per-panel fallback
- [x] Add image-provider error classification and strict no-fallback mode
- [x] Persist image provenance, prompts, relative paths, timing, and fallback in `project.json`
- [x] Add independent text/image Provider controls and status display to Gradio
- [x] Add mocked image HTTP, fallback, security, persistence, and layout tests
- [ ] Add project JSON reload support
- [ ] Add per-panel editing and selective regeneration
- [ ] Add configurable page templates, speech bubbles, and multi-page export
- [ ] Add prompt/version metadata and generation cost or timing telemetry

## Stage 3 — Image Provider 2.0

- [x] Add unified `ImageGenerationRequest` and `ImageGenerationResult`
- [x] Add machine-readable `ImageProviderCapabilities` and model definitions
- [x] Add configuration, authentication, balance, rate-limit, timeout, response,
  content-policy, and unsupported-capability errors
- [x] Reject unsupported advanced parameters instead of silently ignoring them
- [x] Add secure URL download limits, base64 decoding, and Pillow validation
- [x] Add bounded exponential retry for 429, 5xx, connection, and timeout failures
- [x] Keep 400/401/402/403 and content-policy failures non-retryable
- [x] Implement Mock Image Provider
- [x] Implement OpenAI Images generations and edits with multiple images and Mask
- [x] Implement Recraft Image Provider
- [x] Implement Together Image Provider
- [x] Implement SiliconFlow native `image_size`/`batch_size`/`images` protocol
- [x] Implement fal queue submission, status polling, and result retrieval
- [x] Implement ComfyUI workflow submission, history polling, and `/view` download
- [x] Build Provider/model registry metadata for dynamic Gradio controls
- [x] Add advanced image settings, capability display, strict mode, and concurrency
- [x] Add primary → secondary → Mock per-panel fallback chain
- [x] Persist Provider, model, operation, request ID, seed, parameters, timing,
  fallback, and safe errors without base64 or credentials
- [x] Add credential-safe one-image smoke-test script
- [x] Add fully offline HTTP Mock tests for P0 protocols and failure behavior

## Image Provider P1 — not registered until complete

- [ ] Gemini Image Provider
  - Environment: `GEMINI_API_KEY`, `GEMINI_IMAGE_MODEL`
  - Protocol: Google Generative Language `models/{model}:generateContent`;
    normalize image `inlineData` and support reference-image content parts
  - Acceptance: text-to-image, reference image, base64 validation, 401/429/5xx,
    timeout, safety rejection, redaction, and strict-mode tests
- [ ] DashScope Image Provider
  - Environment: `DASHSCOPE_API_KEY`, `DASHSCOPE_IMAGE_MODEL`
  - Protocol: official DashScope image-synthesis/multimodal generation endpoint;
    submit task, poll task status endpoint, then securely download results
  - Acceptance: task ID, terminal success/failure, maximum poll time, URL safety,
    authentication, balance/rate-limit mapping, and Mock HTTP tests
- [ ] Volcengine Ark Image Provider
  - Environment: `ARK_API_KEY`, `ARK_IMAGE_MODEL`
  - Protocol: Ark `/api/v3/images/generations`; normalize URL/base64 and supported
    size/seed/quality fields after reconfirming the selected model documentation
  - Acceptance: request mapping, response normalization, policy/limit errors,
    redaction, retry boundaries, and strict-mode tests
- [ ] Replicate Image Provider
  - Environment: `REPLICATE_API_TOKEN`, `REPLICATE_MODEL`
  - Protocol: `/v1/models/{owner}/{name}/predictions` or deployment prediction;
    follow returned polling/cancel URLs and normalize output URL list
  - Acceptance: asynchronous starting/processing/succeeded/failed/canceled states,
    cancel support, maximum poll time, URL validation, and fully mocked tests
- [ ] xAI Image Provider
  - Environment: `XAI_API_KEY`, `XAI_IMAGE_MODEL`
  - Protocol: xAI `/v1/images/generations`; map supported count/format fields and
    normalize URL/base64 only after reconfirming current official documentation
  - Acceptance: configuration, generation, response validation, error taxonomy,
    redaction, retry boundaries, and strict-mode tests

## Stage 3 — Comic quality P0

- [x] Split script review/confirmation from paid image generation
- [x] Add story bible, factual/causal review, automatic revision, and repair retry
- [x] Add backward-compatible structured speech/thought/narration/sfx items
- [x] Add character positions, speaker anchors, and reserved bubble regions
- [x] Replace the full-width bottom caption bar with comic bubble rendering
- [x] Add language-aware wrapping and fonts for zh-CN, en, and ja-JP
- [x] Reuse full character/style definitions in every image prompt
- [x] Add clean negative-space composition instructions before image generation
- [x] Add editable storyboard table and project JSON reload to Gradio
- [x] Add natural-language story correction and full-storyboard redesign before images
- [x] Persist user story guidance in project JSON and validate revised output
- [x] Accumulate multi-round story revisions instead of replacing earlier constraints
- [x] Add editable final title and non-generic title candidates
- [x] Add selectable manual-review and explicit automatic generation modes
- [x] Add grid, vertical webtoon, and adaptive traditional-page composition
- [x] Add optional inset/split/montage subshots inside one generated panel
- [x] Cap speech tails, omit unanchored tails, and compact narration cards
- [x] Add immersive organic bubbles, text-only narration, rotated SFX, and optional panel numbers
- [x] Prefer low-detail lettering regions using image edge-density scoring
- [x] Keep four-panel traditional pages equal-width and remove blurred ratio padding
- [x] Reuse a strict project-wide palette, rendering, and natural-skin style lock in every image request
- [x] Re-render existing raw panels in another language without new image Provider calls
- [x] Cache multiple lettering localizations in project JSON for free language switching
- [x] Add optional plus-button custom frames while preserving automatic layout defaults
- [x] Validate paired half-row frames before any paid image request
- [x] Generate and letter custom panels at the closest Provider-supported aspect ratio
- [x] Persist and reload custom frame order in project JSON
- [x] Select any custom frame and insert after it or delete it directly
- [x] Move creation controls into a collapsible sidebar with a clearer glass-tech theme
- [x] Replace the five workflow accordions with a settings-only sidebar and visible task hub/tabs
- [x] Make manual/automatic mode switch visible primary actions and valid layout choices
- [x] Hide the custom-frame editor unless manual custom layout is active
- [x] Make storyboard count the single source of truth for every page layout
- [x] Initialize, resize, and cap custom frames to the selected storyboard count
- [x] Add selected-frame type replacement without changing storyboard length
- [x] Promote story redesign, language switching, and export to main workspace tabs
- [x] Accept an optional full story/script before the first storyboard generation
- [x] Use story, character, speaker, scene, and action context for comic localization
- [x] Add first-run guidance and reorder the main workspace around the task sequence
- [x] Add fit-to-window and width-reading preview modes without changing PNG resolution
- [x] Reduce visible UI copy; remove the visually inconsistent light/dark experiment and keep one stable light theme
- [x] Derive image dimensions from page/frame layout and hide low-level controls unless the selected Provider supports them
- [x] Replace technical image labels with user-facing Chinese descriptions and hide unavailable reference/edit inputs
- [x] Export the final composed comic as both PNG and PDF
- [x] Reject unchanged text in manual language mode instead of reporting false success
- [x] Promote one cue-rich panel to a purposeful inset when a text model ignores multi-shot mode
- [x] Display each panel's actual requested generation ratio after rendering
- [x] Preserve Recraft no-Seed behavior and Seed-capable Provider behavior
- [x] Add offline multilingual bubble preview and P0 regression tests

## Stage 3 — Comic quality P1

- [x] Score bubble regions using image edge density
- [ ] Extend placement scoring with subject/face detection and manual overrides
- [ ] Add manual bubble dragging and per-panel position adjustment
- [ ] Add single-panel regeneration
- [x] Add irregular bubble outlines and rotated SFX
- [ ] Add perspective SFX and selectable comic-lettering font packs
- [ ] Add advanced character-reference workflows only for Providers that support them
- [ ] Allow a separately selected script-review Provider
