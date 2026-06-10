---
name: foodtalks-photo-checkin
description: Private FoodTalks photo brand check-in workflow. Use when processing local user photos to identify candidate FoodTalks brands, generate LibreOffice ODS review packs, read user feedback, copy confirmed source photos, and write confirmed brand IDs to Appwrite without keeping sensitive previews or blindly writing unreviewed matches.
---

# FoodTalks Photo Check-in

Use this skill inside `E:\GitHub\foodtalks-checkin` for the local photo-to-Appwrite workflow. The user is privacy-sensitive: avoid exposing secrets, avoid uploading or copying full photo sets, and clean generated previews/request files after each batch.

Current operating rule: run 500-photo batches, generate ODS-only review packs, write Appwrite only from user-confirmed feedback, and keep progress visible through `progress.txt`.

## Paths

- Repo: `E:\GitHub\foodtalks-checkin`
- Source photos: `C:\Users\addAdministrators\Pictures\photos\相册`
- C-drive run root: `C:\Users\addAdministrators\Pictures\photos\photo-runs`
- Confirmed photo copies: `C:\Users\addAdministrators\Pictures\photos\matched-brands`
- Current Appwrite config file: `appwrite-config.js`
- Brand data file: `brand-checkin-data.js`
- Local private environment files:
  - `.venv/foodtalks.env`
  - `.venv/foodtalks-env.ps1`

Never place photo run artifacts on E drive. Do not move or delete source photos.

## Secrets And API Facts

- OpenAI-compatible endpoint uses `OPENAI_BASE_URL`; this project currently uses `http://192.168.124.160:8317/v1`.
- The compatible endpoint does not support OpenAI Batch API, so use `run-sync`.
- Appwrite endpoint/project/database/table are read from `appwrite-config.js`.
- Appwrite writes require `APPWRITE_API_KEY` and `APPWRITE_USER_ID`; load them from local env or process environment only, never committed files.
- `tools.brand_photo_checkin.local_env` loads `.venv/foodtalks.env`; do not print secrets in chat, logs, or summaries.
- Appwrite rows are idempotent by `user_id + brand_id`.

## Batch Workflow

Use 500-photo batches and C-drive run directories. When the user says "next batch" or "continue", find the latest `batch-<start>-<end>` directory under the C-drive run root and start at `<end> + 1`. Name the new directory with an inclusive end, for example offset `3927` becomes `batch-003927-004426`.

```powershell
uv run python -m tools.brand_photo_checkin prepare "C:\Users\addAdministrators\Pictures\photos\相册" --run-dir "<run-dir>" --offset <offset> --limit 500
uv run python -B -m tools.brand_photo_checkin run-sync "<run-dir>" --retries 8 --retry-delay-seconds 10
uv run python -m tools.brand_photo_checkin ingest "<run-dir>"
```

Do not write Appwrite directly from `auto_write.json`. The user must review candidates first.

`prepare` often exceeds the tool timeout while still finishing successfully. If it times out, check that `photos.jsonl`, `batch_requests.jsonl`, and exactly 500 files under `previews/` exist before rerunning.

`run-sync` is resumable. It skips custom IDs already present in `batch_output.jsonl`; if an API/network error interrupts a batch, rerun the same `run-sync` command for the same directory.

While `run-sync` runs, keep the user informed. The progress file is:

```text
<run-dir>\progress.txt
```

It should show phase, status, `progress: completed/total`, skipped, failed, current ID, message, and timestamp. Mention this path when starting a long batch.

Before ingest/review-pack, verify `batch_output.jsonl` has 500 rows, 500 unique `custom_id` values, and no duplicates.

## Review Pack Rules

Generate a review pack only from model/matching candidates, not all photos:

```powershell
uv run python -m tools.brand_photo_checkin.review_pack "C:\Users\addAdministrators\Pictures\photos\相册" --output-dir "<run-dir>\review-pack" --run-dir "<run-dir>" --offset <offset> --limit 500 --columns 4
```

Review pack contents:

- `contact-sheet-001.jpg`: candidate-only higher-resolution thumbnail sheet with index and guessed brand.
- `review_feedback.ods`: primary LibreOffice review file.
- `README.txt`: short local instructions.

Do not ask the user to review non-candidate photos.

The user wants ODS only for review. Do not keep CSV/XLSX review files unless needed temporarily by code; remove generated CSV/XLSX/intermediate reports after the review pack is safely created.

## ODS Feedback Semantics

The ODS table must use this simple schema:

`编号 / 正确? / 候选品牌 / 识别文字 / 图片路径`

Interpretation:

- `正确?` blank by default.
- `正确? = ✓`: candidate brand is correct; write candidate brand.
- `正确?` blank: candidate is wrong or unconfirmed; skip; do not write or copy.

Do not use the older `correct / wrong_brand / no_brand` dropdown unless reading an old review file. The code remains backward-compatible, but new review packs must use the single-check workflow.

If the user says an unmarked index is actually another brand, manually inspect that ODS row/contact sheet item and resolve the corrected brand. The current ODS schema has no dedicated correction column, so the correction may be in the chat message or typed into the `识别文字` column; do not rely only on `tools.brand_photo_checkin.feedback` to capture it.

## Applying Feedback

After the user fills `review_feedback.ods`, read it, copy confirmed source photos, and create the approved JSON:

```powershell
uv run python -m tools.brand_photo_checkin.feedback "C:\Users\addAdministrators\Pictures\photos\photo-runs\batch-000927-001426\review-pack\review_feedback.ods" --copy-dir "C:\Users\addAdministrators\Pictures\photos\matched-brands" --output-json "C:\Users\addAdministrators\Pictures\photos\photo-runs\batch-000927-001426\approved_feedback.json" --checked-only --skip-unresolved
```

If the feedback command reports fewer rows than expected, inspect the ODS `content.xml` or use `read_feedback_ods` to see the raw row values before writing anything.

If a brand name resolves to multiple `brand_id` values, do not guess unless the photo content makes the product category clear. Otherwise ask the user which `brand_id`/category is intended. Examples from prior batches:

- `维他奶`: use `45` when the visible product is soy milk/plant-based drink.
- `蜜雪冰城`: use `89` for tea drink chain, `141` only for `幸运咖`.
- `可口可乐`: use `22` for classic Coke cola, not other Coca-Cola sub-brands.
- `蒙牛`: choose by product category, e.g. `255` for ice cream/cold dessert, `348` for low-temperature yogurt, `303` for normal temperature milk.
- `UCC悠诗诗`: choose by product category, e.g. `168` for ready-to-drink/coffee machine context, `149` for instant/retail coffee.
- If the corrected brand is missing from `brand-checkin-data.js` (for example `比星咖啡` in a prior batch), do not write a substitute brand ID.

Confirmed photos are copied under `matched-brands\brand-<id>-<label>\`. Only confirmed rows get copied.

## Appwrite Write

Write only rows from `approved_feedback.json`. Use Appwrite API key in memory/environment and verify afterward with a read query. Do not write unchecked rows.

Required row fields:

- `user_id`
- `brand_id`
- `checked_at`

Use permissions for the target user:

- `read("user:<APPWRITE_USER_ID>")`
- `update("user:<APPWRITE_USER_ID>")`
- `delete("user:<APPWRITE_USER_ID>")`

Always generate a write log in the run directory and report the written brand IDs.

## Cleanup

After each batch review pack is safely created, delete sensitive intermediate artifacts and reports:

```powershell
uv run python -m tools.brand_photo_checkin cleanup-run "<run-dir>" --no-keep-reports
```

Also remove `run-sync*.log` files after successful processing unless they are needed for debugging.

Keep:

- `review-pack\review_feedback.ods`
- `review-pack\contact-sheet-001.jpg`
- `review-pack\README.txt`
- `progress.txt`
- `progress.json`
- `approved_feedback.json` and `appwrite_feedback_write_log.jsonl` after the user has confirmed and Appwrite has been written

Remove:

- `previews\`
- `photos.jsonl`
- `batch_requests.jsonl`
- `batch_output.jsonl`
- `auto_write.csv/json`
- `needs_review.csv`
- `unmatched.csv`
- CSV/XLSX review artifacts
- OpenAI request/response/log files

Do not delete source photos. Do not delete review packs or approved feedback unless the user explicitly asks.

## Verification

For code changes, run:

```powershell
uv run basedpyright tools tests typings
uv run ruff check tools tests
uv run pytest
```

For review files, verify the ODS contains native validation for the `✓` marker and no old `wrong_brand/no_brand` options.
