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

### Org lookup

The Redash instance (`query.smartnews.net`) sits behind an Okta auth-proxy that ignores the API key, so direct programmatic fetches fail. Workaround per month:

1. Open Redash query [#74157](https://query.smartnews.net/queries/74157) in your browser (Okta-authenticated).
2. Click **Download → CSV**.
3. Save it as `<out>/org_lookup_<month>.csv` (e.g. `reports/2026-04/org_lookup_2026-04.csv`).

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

## Outputs

In `--out`:

- `sessions.parquet` — every detected session (one row per session)
- `sampled_sessions.parquet` — the sampled subset, same schema
- `org_lookup_<month>.csv` — cached Redash export
- `run.log` — text log of counts at each step

## Scope

This iteration covers §11.2–11.8 of the design doc — S3 ingest → org join → session detection → stratified sampling. Steps 5–7 (LLM classification, appendix.csv, report.md) are deferred.
