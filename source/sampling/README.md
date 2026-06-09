# Bedrock Log Sampler

Monthly sampler for CCE Bedrock invocation logs. See `../../bedrock-sampling-logs.md` for the full design.

This is a self-contained Poetry sub-project so its heavy deps (pandas, pyarrow) don't leak into the main `ccwb` package or the credential-process binary.

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
`appendix.csv` → `report.md`):

```bash
poetry run bedrock-log-sampler --month 2026-04 --out ./reports/2026-04/ --classify
```

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
| `--classify` | off | run steps 5–7 (Sonnet classification + appendix + report) |
| `--sonnet-model` | `global.anthropic.claude-sonnet-4-6` | model for classification + report |
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
segmentation, `appendix.csv`, `report.md`) run with `--classify`. The classification taxonomy is the
4-pillar / 16-leaf cognitive model from §6 of the design doc.
