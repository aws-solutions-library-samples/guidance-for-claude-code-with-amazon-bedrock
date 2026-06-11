# Bedrock Log Sampler

Monthly sampler for CCE Bedrock invocation logs. See `../../bedrock-sampling-logs.md` for the full design.

This is a self-contained Poetry sub-project so its heavy deps (pandas, pyarrow) don't leak into the main `ccwb` package or the credential-process binary.

## What it does

Once a month, read every Claude Code / Bedrock interaction, figure out **what people used AI for**,
and produce a leadership-friendly report — without ever exposing anyone's transcript text. It's a
7-step pipeline; steps 1–4 always run, steps 5–7 run with `--classify`:

| Step | Does | Model |
|---|---|---|
| 1. S3 ingest | List + download the month's invocation-log files from the audit bucket, parse each call into a row (who, when, model, tokens, body location). Glacier-archived files are skipped. | — |
| 2. Org join | Attach division/department/team from `org-lookup.csv` by email prefix; unmatched → `(unknown)`. | — |
| 3. Session detection | Group each user's back-to-back calls into sessions (new session after a 30-min idle gap). | — |
| 4. Stratified sampling | Pick a representative per-division subset (8%, floor 20, cap 200, fixed seed) so classification stays affordable. | — |
| 5. Classification | For each sampled session: fetch the transcript, segment it into activity *spans* against the 4-pillar / 16-leaf taxonomy, plus friction signals + a one-line summary. | **Sonnet** |
| 6. `appendix.csv` | One privacy-safe row per session: hashed user id, org metadata, span/friction counts. **No transcript text.** | — |
| 7. `report.md` | Roll the appendix into aggregates, then write the two-part Markdown report (exec brief + per-division analyst tables). | **Opus** |

### Design choices

- **Two models on purpose.** Step 5 fans out ~700 calls, so it runs on the cheaper **Sonnet**. Step 7
  is a single high-stakes call, so it runs on **Opus** — Opus follows the length/format instructions,
  whereas Sonnet over-generates the per-division tables and truncates the report. Override with
  `--sonnet-model` / `--report-model`.
- **Math in Python, not in the model.** Per-activity shares and session counts are computed in code and
  handed to the report model to *transcribe*, so it can't invent numbers (the prompt also says "use only
  the aggregates provided").
- **Privacy by construction.** Transcripts are read transiently only during step 5; nothing from step 6
  on contains raw text or un-hashed user ids.
- **Cheap iteration.** Steps 1–5 are the slow/expensive part. `--report-only` rewrites just `report.md`
  from an existing `appendix.csv` (one Opus call) so the report can be tuned without a full re-run.

## Setup

```bash
cd source/sampling
poetry install
```

Same command works on a laptop or in a batch container — the lockfile pins all transitive deps.

## Run

AWS credentials must be exported (e.g. `source ../../env.sh` for local dev with `genai-studio-dev` admin creds):

```bash
mkdir -p ./reports/2026-04/
# Manually drop the org-lookup CSV — see "Org lookup" below
cp ~/Downloads/org_lookup.csv ./reports/2026-04/org_lookup_2026-04.csv

poetry run bedrock-log-sampler --month 2026-04 --out ./reports/2026-04/
```

By default this runs steps 1–4 (S3 ingest → org join → session detection → sampling) and writes the
parquet files. Add `--classify` to also run steps 5–7 (fetch transcripts → Sonnet span segmentation →
`appendix.csv` → Opus `report.md`):

```bash
poetry run bedrock-log-sampler --month 2026-04 --out ./reports/2026-04/ --classify
```

> **Two models, on purpose.** Step 5 (per-session classification, ~700 calls) runs on **Sonnet**
> (`--sonnet-model`) — cheap and good enough for span segmentation. Step 7 (the single `report.md`
> call) runs on **Opus** (`--report-model`). Opus follows the length/format instructions; Sonnet
> over-generates the per-division tables and truncates the report mid-way.

### Regenerate just the report (`--report-only`)

To iterate on the report prompt or model **without** re-ingesting S3 or re-classifying every session,
run `--report-only`. It reads the existing `<out>/appendix.csv` and rewrites only `report.md` — one
Bedrock (Opus) call, ~90s, ~no cost:

```bash
poetry run bedrock-log-sampler --month 2026-05 --out ./reports/2026-05/ --report-only
```

Requires a prior `--classify` run to have produced `appendix.csv` (the script errors if it's missing).
This is the normal way to refresh a report after a prompt/format change — a full re-run is only needed
when the underlying sampling or classification changes.

> **Run as an admin/analyst identity, not the end-user CCE role.** `--classify` reads transcript
> bodies from the logs bucket; the `BedrockOktaFederatedRole` has no S3 read there by design. The
> `genai-studio-dev` admin SSO role (`AWSReservedSSO_aft-power-user`) works.
>
> **Run within ~30 days of the target month.** Bodies older than the 30-day S3 lifecycle window are in
> Glacier and return `InvalidObjectState`; those sessions are flagged `archived (Glacier)` in the
> appendix and skipped (restore them first if you need older months).

### Org lookup

The Redash instance (`query.smartnews.net`) sits behind an Okta auth-proxy that ignores the API key, so direct programmatic fetches fail. Workaround per month:

1. Open Redash query [#74157](https://query.smartnews.net/queries/74157) in your browser (Okta-authenticated).
2. Click **Download → CSV**.
3. Save it as `<out>/org-lookup.csv` (e.g. `reports/2026-05/org-lookup.csv`). The filename is static —
   it already lives inside the per-month `<out>` folder, so no month suffix is needed.

The CSV must have an `email` column; any of `division`, `department`, `team`, `group`, `org1`, `org2`,
`org 3` present are carried through to the session/appendix rows **as-is** (e.g. `org 3` → `org_3`; no
renaming to team/group). `division` drives the stratified sampling and the per-division report
breakdown; unmatched users fall to `(unknown)`.

The script checks for that file first and only attempts a Redash fetch if it's missing AND `--redash-api-key` was passed. Once a service account or proxy bypass is set up, drop the API key in via `--redash-api-key` / `REDASH_API_KEY` and the manual step goes away.

Knobs:

| Flag | Default | Notes |
|---|---|---|
| `--month` | required | `YYYY-MM`, the month to process |
| `--out` | required | output dir, created if missing |
| `--bucket` | `sn-cce-bedrock-invocation-logs-136113531821` | |
| `--region` | `us-west-2` | S3 prefix region |
| `--idle-gap-min` | 30 | session boundary gap |
| `--sample-pct` | 0.08 | per-division sample fraction |
| `--cap` | 200 | max sampled sessions per division |
| `--floor` | 20 | min sampled sessions per division |
| `--seed` | 42 | reproducible sampling |
| `--limit-objects` | (none) | debug knob: read at most N S3 objects |
| `--redash-api-key` | env `REDASH_API_KEY` | API key for Redash query #74157 |
| `--classify` | off | run steps 5–7 (classification + appendix + report) |
| `--report-only` | off | skip steps 1–6; regenerate `report.md` from existing `appendix.csv` |
| `--sonnet-model` | `global.anthropic.claude-sonnet-4-6` | model for step 5 per-session classification |
| `--report-model` | `global.anthropic.claude-opus-4-6-v1` | model for step 7 report generation (Opus) |
| `--bedrock-region` | `us-west-2` | region for bedrock-runtime calls |
| `--max-transcript-chars` | 320000 | middle-truncate transcripts over this (~80k tokens) |
| `--classify-concurrency` | 4 | parallel Bedrock classification calls |
| `--hash-salt` | env `HASH_SALT` / `cce-sampler` | salt for hashing user ids in appendix.csv |

## Outputs

In `--out`:

- `sessions.parquet` — every detected session (one row per session)
- `sampled_sessions.parquet` — the sampled subset, same schema
- `org-lookup.csv` — the org-metadata export you dropped in (input, not generated)
- `run.log` — text log of counts at each step

With `--classify`, additionally:

- `appendix.csv` — one row per sampled session: hashed user id, org metadata, `span_count`,
  `spans_json`, `activity_freq_json`, `pillar_freq_json`, `friction_signals`, `one_line_summary`,
  `classify_error`. **No transcript text.**
- `report.md` — the executive report (exec brief + detailed analyst section).

## Scope

Implements the full design (§5 steps 1–7). Steps 1–4 run by default; steps 5–7 (Sonnet span
segmentation → `appendix.csv` → Opus `report.md`) run with `--classify`. The classification taxonomy
is the 4-pillar / 16-leaf cognitive model from §6 of the design doc.
