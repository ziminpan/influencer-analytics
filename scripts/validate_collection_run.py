#!/usr/bin/env python3
"""Validate a collection checkpoint against the creator database and summary.

This script is intentionally read-only. It catches incomplete queues, duplicate
profile URLs, missing database rows, and stale summaries before final delivery.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


URL_FIELDS = ("profile_url", "instagram_url", "collabstr_url")


def normalize_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def record_url(record: dict) -> str:
    for field in URL_FIELDS:
        normalized = normalize_url(str(record.get(field, "")))
        if normalized:
            return normalized
    return ""


def validate(checkpoint: Path, database: Path, expected: int, summary: Path | None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        records = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"checkpoint unreadable: {exc}"], "warnings": []}

    if not isinstance(records, list):
        return {"ok": False, "errors": ["checkpoint must be a JSON array"], "warnings": []}

    if len(records) != expected:
        errors.append(f"checkpoint count {len(records)} != expected {expected}")

    urls = [record_url(record) for record in records]
    missing_url_rows = [index + 1 for index, value in enumerate(urls) if not value]
    if missing_url_rows:
        errors.append(f"checkpoint rows missing profile URL: {missing_url_rows}")

    duplicates = sorted(value for value, count in Counter(urls).items() if value and count > 1)
    if duplicates:
        errors.append(f"duplicate checkpoint URLs: {duplicates}")

    missing_dates = [index + 1 for index, record in enumerate(records) if not record.get("collected_at")]
    if missing_dates:
        errors.append(f"checkpoint rows missing collected_at: {missing_dates}")

    try:
        with database.open("r", encoding="utf-8-sig", newline="") as handle:
            db_rows = list(csv.DictReader(handle))
    except OSError as exc:
        return {"ok": False, "errors": [f"database unreadable: {exc}"], "warnings": warnings}

    db_by_url: dict[str, list[dict]] = {}
    for row in db_rows:
        normalized = normalize_url(row.get("profile_url", ""))
        if normalized:
            db_by_url.setdefault(normalized, []).append(row)

    missing_db = sorted(value for value in urls if value and value not in db_by_url)
    if missing_db:
        errors.append(f"checkpoint URLs missing from database: {missing_db}")

    duplicate_db = sorted(value for value in urls if value and len(db_by_url.get(value, [])) > 1)
    if duplicate_db:
        errors.append(f"checkpoint URLs duplicated in database: {sorted(set(duplicate_db))}")

    matched = [db_by_url[value][0] for value in urls if value in db_by_url and len(db_by_url[value]) == 1]
    status_counts = dict(sorted(Counter(row.get("status", "") or "<blank>" for row in matched).items()))
    public_email_count = sum(bool((row.get("email") or "").strip()) for row in matched)

    if summary is not None:
        if not summary.exists():
            errors.append(f"summary missing: {summary}")
        elif summary.stat().st_mtime < checkpoint.stat().st_mtime:
            errors.append("summary is older than the latest checkpoint")

    return {
        "ok": not errors,
        "checkpoint_count": len(records),
        "database_matches": len(matched),
        "status_counts": status_counts,
        "public_email_count": public_email_count,
        "errors": errors,
        "warnings": warnings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--expected", required=True, type=int)
    parser.add_argument("--summary", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate(args.checkpoint, args.db, args.expected, args.summary)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
