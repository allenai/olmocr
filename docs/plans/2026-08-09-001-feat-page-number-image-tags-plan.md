---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
type: feat
created: 2026-08-09
---

# feat: Add real page number to figure/chart image tags

**Target repo:** olmocr (this repo — fork of allenai/olmocr)

---

## Summary

olmOCR's live pipeline instructs the model to label extracted figures/charts with a markdown image tag of the form `![alt](page_startx_starty_width_height.png)`. The tag carries no page number, so a caller processing a multi-page document cannot tell which page a given figure came from. This plan changes the instructed tag format for the **live inference prompt** to bake in the real page number (`![alt](<page_num>_startx_starty_width_height.png)`), so the model copies an actual number it's told rather than being asked to invent one it has no way to know.

**Revised from the original request during planning** (see Key Technical Decisions, KTD1): a first pass considered a literal find-and-replace of the string `page_startx_starty_width_height.png` → `page_number_startx_starty_width_height.png` across all 4 occurrences in `olmocr/prompts/prompts.py`. Feasibility review found this would not work: the model is never given the actual page number anywhere in the prompt or image input, so it has no value to substitute for `page_number` — renaming the placeholder token achieves nothing the issue actually wants. The fix below instead threads the real, already-known page index into the one prompt used by the live pipeline.

## Problem Frame

- `build_no_anchoring_v4_yaml_prompt()` (`olmocr/prompts/prompts.py:164`) is the prompt used for every live inference call (`olmocr/pipeline.py:139`, inside `build_page_query`). It takes no arguments, even though its caller, `build_page_query(local_pdf_path, page, ...)` (`olmocr/pipeline.py:106`), already has the real page number in scope as `page` — it just never forwards it into the prompt.
- The other 3 occurrences of the same tag pattern (`build_openai_silver_data_prompt_v2`, `_v2_simple`, `_v3_simple`) are used only to generate training/silver data from **isolated single-page PDFs** (`olmocr/data/clean_olmocrmix.py`'s `render_single_page_pdf` always renders "page 1 since we validated it's a single-page PDF"). There is no real multi-page context there — a "page number" would always be `1` and would carry no information. Threading a real page number into those prompts would not serve the issue's goal and is out of scope (see Scope Boundaries).
- No code anywhere in the repo parses the emitted filename pattern back out (confirmed via repo-wide search) — it's purely a model instruction, not a contract consumed elsewhere. This keeps the blast radius of the fix contained to `prompts.py` and one call site in `pipeline.py`.

## Requirements

- R1: The live pipeline's figure/chart tag instruction must bake in the actual page number for the page currently being processed, so the model has a concrete value to copy rather than a token it must invent.
- R2: The change must not alter any other instruction text in the affected prompt string.
- R3: The training-data-only prompt variants (v2, v2_simple, v3_simple) are left unchanged — see Scope Boundaries.

## Key Technical Decisions

- **KTD1 (revised from original request): Bake the real page number into the prompt string instead of renaming a placeholder token.** Chosen over the originally-requested literal `page` → `page_number` string rename, because feasibility review confirmed the model is never given an actual page number value anywhere in its input — renaming the token would ask the model to invent a number it cannot know, producing the same unusable output the issue is trying to fix. Passing the real, already-available `page` value into the prompt (the same way `page_width`/`page_height` are already interpolated into the `_v2_simple`/`_v3_simple` prompts) makes the output deterministic and correct.
- **KTD2: Scope the change to `build_no_anchoring_v4_yaml_prompt` and its one call site, not the training-data prompt variants.** Those variants process single, already-isolated pages with no multi-page context (always effectively "page 1" — see Problem Frame), so a real page number there would always be `1` and adds no value. Renaming their placeholder without a real value would recreate the same "model invents a number" problem this plan is fixing. Also out of scope: `olmocr/data/clean_olmocrmix.py:120`, a historical dataset-cleaning script disconnected from the live pipeline.

## Implementation Units

### U1. Thread the real page number into the live pipeline prompt

**Goal:** `build_no_anchoring_v4_yaml_prompt` accepts the page number and interpolates it directly into the instructed image tag filename; its one caller passes the real value it already has.

**Requirements:** R1, R2

**Dependencies:** None

**Files:**
- `olmocr/prompts/prompts.py` (function `build_no_anchoring_v4_yaml_prompt`, ~line 164)
- `olmocr/pipeline.py` (call site inside `build_page_query`, ~line 139)
- `olmocr/bench/runners/run_server.py` (call site in `run_server`, ~line 59 — already receives a real `page_num` parameter)
- `olmocr/train/grpo_train.py` (call site in the GRPO dataset `__getitem__`, ~line 523 — already has the real page number as `page_num = sample["page"]`)

**Approach:**
- Add a `page_num: int = 1` parameter to `build_no_anchoring_v4_yaml_prompt`. Default of `1` preserves current behavior for the two remaining callers that only ever process an isolated single page (`olmocr/train/dataloader.py:244`, `scripts/hf_local_test.py:30` — both left unchanged, matching this repo's existing "always page 1" convention for single-page contexts at `dataloader.py:194`).
- Replace the literal `page_startx_starty_width_height.png` in its instruction string with an f-string interpolating `page_num`, e.g. `f"{page_num}_startx_starty_width_height.png"`, following the same interpolation style already used for `page_width`/`page_height` in `build_openai_silver_data_prompt_v2_simple`.
- Update the call site at `olmocr/pipeline.py:139` to `build_no_anchoring_v4_yaml_prompt(page_num=page)`, using the `page` parameter `build_page_query` already receives.
- Update `run_server.py` and `grpo_train.py` to pass their already-available real page number explicitly, so bench and RL-training outputs aren't silently mislabeled as page 1 the same way the live pipeline was.

**Test scenarios:**
- Happy path: calling `build_no_anchoring_v4_yaml_prompt(page_num=3)` returns a string containing `3_startx_starty_width_height.png` and no longer contains the bare `page_startx_starty_width_height.png` literal.
- Edge case: `page_num=1` (the common case, first page) produces `1_startx_starty_width_height.png`, not an off-by-one value — confirms no accidental 0-indexing/1-indexing shift versus the `page` value passed by `build_page_query`.
- Regression: `build_page_query`'s call to `build_no_anchoring_v4_yaml_prompt` still returns a well-formed request dict (no signature mismatch); import smoke check on both modules.

**Verification:** `python -c "from olmocr.prompts.prompts import build_no_anchoring_v4_yaml_prompt; assert '3_startx_starty_width_height.png' in build_no_anchoring_v4_yaml_prompt(page_num=3)"` succeeds, and `python -c "import olmocr.pipeline"` succeeds with no exceptions.

## Scope Boundaries

### Deferred to Follow-Up Work

- `build_openai_silver_data_prompt_v2`, `_v2_simple`, `_v3_simple` in `olmocr/prompts/prompts.py` — same tag pattern, but used only for single-page, page-number-less training-data generation (see KTD2). Not changed here.
- `olmocr/data/clean_olmocrmix.py:120` — historical dataset-cleaning script, not the live pipeline.
- No change to any downstream figure-extraction tooling, since none currently exists in this repo to consume the tag format.

## Definition of Done

- `build_no_anchoring_v4_yaml_prompt` takes `page_num` and emits it in the instructed tag.
- `olmocr/pipeline.py` passes the real page number at the one call site.
- Verification checks in U1 pass.
- No other files modified.
