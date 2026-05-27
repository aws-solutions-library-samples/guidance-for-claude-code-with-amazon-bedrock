"""Monthly sampler for CCE Bedrock invocation logs.

Implements steps 1-4 of the design in `bedrock-sampling-logs.md` (§5.1-5.4):
S3 ingest → org join → session detection → stratified sampling.

Steps 5-7 (LLM classification, appendix.csv, report.md) are out of scope here.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import boto3
import pandas as pd
import requests
from botocore.config import Config

DEFAULT_BUCKET = "sn-cce-bedrock-invocation-logs-136113531821"
DEFAULT_REGION = "us-west-2"
DEFAULT_ACCOUNT = "136113531821"
REDASH_QUERY_URL = "https://query.smartnews.net/api/queries/74157/results.csv"

log = logging.getLogger("bedrock_log_sampler")


@dataclass
class Args:
    month: str
    out: Path
    bucket: str
    region: str
    idle_gap_min: int
    sample_pct: float
    cap: int
    floor: int
    seed: int
    limit_objects: int | None
    redash_api_key: str
    s3_concurrency: int


def parse_args(argv: list[str] | None = None) -> Args:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--month", required=True, help="YYYY-MM, e.g. 2026-04")
    p.add_argument("--out", required=True, type=Path, help="Output directory")
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--region", default=DEFAULT_REGION, help="S3 prefix region")
    p.add_argument("--idle-gap-min", type=int, default=30)
    p.add_argument("--sample-pct", type=float, default=0.08)
    p.add_argument("--cap", type=int, default=200)
    p.add_argument("--floor", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--limit-objects", type=int, default=None,
                   help="Debug: read at most N S3 objects")
    p.add_argument("--redash-api-key", default=os.environ.get("REDASH_API_KEY"),
                   help="Redash API key (or REDASH_API_KEY env var). "
                   "Not required if <out>/org_lookup_<month>.csv already exists.")
    p.add_argument("--s3-concurrency", type=int, default=8,
                   help="Parallel S3 GETs for log files")
    ns = p.parse_args(argv)

    try:
        datetime.strptime(ns.month, "%Y-%m")
    except ValueError:
        p.error("--month must be YYYY-MM")

    return Args(**vars(ns))


# -- Step 1: S3 ingest --------------------------------------------------------

def list_log_objects(s3, bucket: str, region: str, month: str,
                     limit: int | None) -> list[str]:
    """List all metadata JSONL keys for the target month, skipping data/."""
    year, mon = month.split("-")
    prefix = (f"{region}/claude-code/AWSLogs/{DEFAULT_ACCOUNT}/"
              f"BedrockModelInvocationLogs/{region}/{year}/{mon}/")
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if "/data/" in k:
                continue  # body files, fetched on demand later
            if not k.endswith(".json.gz"):
                continue
            keys.append(k)
            if limit is not None and len(keys) >= limit:
                return keys
    return keys


def _parse_one_object(s3, bucket: str, key: str) -> list[dict]:
    """Download one .json.gz, parse JSONL, return flat dict rows."""
    obj = s3.get_object(Bucket=bucket, Key=key)
    raw = obj["Body"].read()
    try:
        text = gzip.decompress(raw).decode("utf-8")
    except OSError:
        log.warning("not gzipped, skipping: %s", key)
        return []

    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        identity_arn = (rec.get("identity") or {}).get("arn")
        ts = rec.get("timestamp")
        if not identity_arn or not ts:
            continue
        inp = rec.get("input") or {}
        out = rec.get("output") or {}
        # Bedrock externalizes large bodies to S3; small bodies are inlined as
        # `inputBodyJson` / `outputBodyJson`. Capture whichever form is present.
        inp_inline = inp.get("inputBodyJson")
        out_inline = out.get("outputBodyJson")
        rows.append({
            "timestamp": ts,
            "request_id": rec.get("requestId"),
            "model_id": rec.get("modelId"),
            "identity_arn": identity_arn,
            "input_body_s3_path": inp.get("inputBodyS3Path"),
            "output_body_s3_path": out.get("outputBodyS3Path"),
            "input_body_inline": (json.dumps(inp_inline)
                                  if inp_inline is not None else None),
            "output_body_inline": (json.dumps(out_inline)
                                   if out_inline is not None else None),
            "input_tokens": inp.get("inputTokenCount"),
            "cache_read_tokens": inp.get("cacheReadInputTokenCount"),
            "cache_write_tokens": inp.get("cacheWriteInputTokenCount"),
            "output_tokens": out.get("outputTokenCount"),
            "inference_region": rec.get("inferenceRegion"),
        })
    return rows


def ingest_s3(s3, bucket: str, region: str, month: str,
              limit: int | None, concurrency: int) -> pd.DataFrame:
    keys = list_log_objects(s3, bucket, region, month, limit)
    log.info("listed %d log objects under bucket=%s month=%s", len(keys), bucket, month)
    if not keys:
        return pd.DataFrame()

    all_rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_parse_one_object, s3, bucket, k): k for k in keys}
        done = 0
        for fut in as_completed(futures):
            rows = fut.result()
            all_rows.extend(rows)
            done += 1
            if done % 50 == 0 or done == len(keys):
                log.info("parsed %d/%d objects, %d invocations so far",
                         done, len(keys), len(all_rows))

    df = pd.DataFrame(all_rows)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["user_prefix"] = df["identity_arn"].str.rsplit("/", n=1).str[-1]
    df["user_prefix"] = df["user_prefix"].str.removeprefix("claude-code-")
    return df


# -- Step 2: Org metadata join ------------------------------------------------

def fetch_org_lookup(out_dir: Path, month: str, api_key: str | None) -> pd.DataFrame:
    """Load org lookup CSV. Prefers a cached file at <out>/org_lookup_<month>.csv;
    falls back to fetching from Redash if --redash-api-key was provided."""
    cache = out_dir / f"org_lookup_{month}.csv"
    if cache.exists():
        log.info("reusing cached org lookup at %s", cache)
        return pd.read_csv(cache)

    if not api_key:
        raise RuntimeError(
            f"No org lookup found at {cache} and --redash-api-key not provided.\n"
            f"Workaround: download Redash query #74157 as CSV in your browser "
            f"and save it as {cache}, then re-run."
        )

    log.info("fetching org lookup from Redash")
    resp = requests.get(REDASH_QUERY_URL, params={"api_key": api_key}, timeout=60)
    resp.raise_for_status()
    cache.write_bytes(resp.content)
    log.info("wrote org lookup cache: %s (%d bytes)", cache, len(resp.content))
    return pd.read_csv(cache)


def join_org(invocations: pd.DataFrame, org: pd.DataFrame) -> pd.DataFrame:
    """Left-join invocations on email_prefix → division/department/team/group."""
    if invocations.empty:
        return invocations

    org = org.copy()
    # Tolerate column-name variations from Redash; we expect 'email' at minimum.
    org.columns = [c.strip().lower() for c in org.columns]
    if "email" not in org.columns:
        raise RuntimeError(
            f"org lookup CSV missing 'email' column; got {list(org.columns)}")
    org["user_prefix"] = (
        org["email"].astype(str).str.split("@", n=1).str[0].str.lower()
    )
    keep = ["user_prefix"] + [c for c in ("division", "department", "team", "group")
                              if c in org.columns]
    org = org[keep].drop_duplicates(subset=["user_prefix"], keep="first")

    merged = invocations.merge(org, on="user_prefix", how="left")
    for col in ("division", "department", "team", "group"):
        if col not in merged.columns:
            merged[col] = "(unknown)"
        else:
            merged[col] = merged[col].fillna("(unknown)")
    return merged


# -- Step 3: Session detection -----------------------------------------------

def detect_sessions(invocations: pd.DataFrame, idle_gap_min: int) -> pd.DataFrame:
    """One row per session, with carrier S3 paths for transcript fetch later."""
    if invocations.empty:
        return invocations

    df = invocations.sort_values(["user_prefix", "timestamp"]).reset_index(drop=True)
    gap = df.groupby("user_prefix")["timestamp"].diff()
    new_session = (gap.isna()) | (gap > pd.Timedelta(minutes=idle_gap_min))
    df["session_idx"] = new_session.groupby(df["user_prefix"]).cumsum().astype(int)
    df["session_id"] = df["user_prefix"] + ":" + df["session_idx"].astype(str)

    # Aggregate per session.
    g = df.groupby("session_id", sort=False)
    agg = g.agg(
        user_prefix=("user_prefix", "first"),
        division=("division", "first"),
        department=("department", "first"),
        team=("team", "first"),
        group=("group", "first"),
        start_ts=("timestamp", "min"),
        end_ts=("timestamp", "max"),
        invocation_count=("request_id", "count"),
        total_input_tokens=("input_tokens", "sum"),
        total_cache_read_tokens=("cache_read_tokens", "sum"),
        total_cache_write_tokens=("cache_write_tokens", "sum"),
        total_output_tokens=("output_tokens", "sum"),
        models=("model_id", lambda s: sorted(set(x for x in s if x))),
    )
    agg["duration_min"] = (
        (agg["end_ts"] - agg["start_ts"]).dt.total_seconds() / 60.0
    )

    # Carrier = last invocation per session (max timestamp).
    last_idx = g["timestamp"].idxmax()
    carrier = df.loc[last_idx, [
        "session_id", "request_id",
        "input_body_s3_path", "output_body_s3_path",
        "input_body_inline", "output_body_inline",
    ]].rename(columns={
        "request_id": "carrier_request_id",
        "input_body_s3_path": "carrier_input_body_s3_path",
        "output_body_s3_path": "carrier_output_body_s3_path",
        "input_body_inline": "carrier_input_body_inline",
        "output_body_inline": "carrier_output_body_inline",
    }).set_index("session_id")

    sessions = agg.join(carrier).reset_index()

    assert (sessions["duration_min"] >= 0).all(), "negative session duration"
    assert sessions["session_id"].notna().all()
    return sessions


# -- Step 4: Stratified sampling ---------------------------------------------

def stratified_sample(sessions: pd.DataFrame, pct: float, cap: int, floor: int,
                      seed: int) -> pd.DataFrame:
    if sessions.empty:
        return sessions

    parts: list[pd.DataFrame] = []
    for div, group in sessions.groupby("division", sort=False):
        n_total = len(group)
        n = max(min(round(n_total * pct), cap), min(floor, n_total))
        n = min(n, n_total)
        sample = group.sample(n=n, random_state=seed) if n > 0 else group.iloc[0:0]
        parts.append(sample)
        log.info("division %s: %d sessions → sampled %d", div, n_total, n)
    return pd.concat(parts).reset_index(drop=True)


# -- Driver -------------------------------------------------------------------

def setup_logging(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(message)s"
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(out_dir / "run.log", mode="w"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.out)
    log.info("starting bedrock_log_sampler month=%s out=%s", args.month, args.out)

    s3 = boto3.client(
        "s3",
        region_name=args.region,
        config=Config(retries={"max_attempts": 6, "mode": "adaptive"}),
    )

    invocations = ingest_s3(s3, args.bucket, args.region, args.month,
                            args.limit_objects, args.s3_concurrency)
    log.info("step 1 complete: %d invocations", len(invocations))
    if invocations.empty:
        log.warning("no invocations found, exiting")
        return 0

    org = fetch_org_lookup(args.out, args.month, args.redash_api_key)
    invocations = join_org(invocations, org)
    matched = (invocations["division"] != "(unknown)").sum()
    log.info("step 2 complete: org join hit %d/%d (%.1f%%)",
             matched, len(invocations), 100.0 * matched / len(invocations))

    sessions = detect_sessions(invocations, args.idle_gap_min)
    log.info("step 3 complete: %d sessions across %d users",
             len(sessions), sessions["user_prefix"].nunique())

    sampled = stratified_sample(sessions, args.sample_pct, args.cap, args.floor,
                                args.seed)
    log.info("step 4 complete: %d sampled sessions", len(sampled))

    sessions_path = args.out / "sessions.parquet"
    sampled_path = args.out / "sampled_sessions.parquet"
    sessions.to_parquet(sessions_path, index=False)
    sampled.to_parquet(sampled_path, index=False)
    log.info("wrote %s (%d rows)", sessions_path, len(sessions))
    log.info("wrote %s (%d rows)", sampled_path, len(sampled))

    print()
    print(f"Month:               {args.month}")
    print(f"Invocations parsed:  {len(invocations):>8d}")
    print(f"Sessions detected:   {len(sessions):>8d}")
    print(f"Sessions sampled:    {len(sampled):>8d}")
    print(f"Unique users:        {sessions['user_prefix'].nunique():>8d}")
    print(f"Divisions covered:   {sessions['division'].nunique():>8d}")
    print(f"Output:              {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
