#!/usr/bin/env python3
"""Apply a reviewed outreach-status policy to a creator CSV.

The script changes only ``status`` and appends an audit note. It never changes
approval, quotes, contact history, or machine-collected fields. Dry-run is the
default; pass ``--apply`` to write atomically.
"""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
from pathlib import Path


DEFAULT_LEGACY_STATUSES = {
    "待审",
    "待查",
    "备选",
    "观察",
    "备选·候选转放大器池",
}
AUDIT_NOTE = "2026-08-07 direction-only政策：方向未明确不符，status统一改为待触达；原风险保留在approval/notes"


def parse_ids(value: str) -> set[str]:
    return {part.strip() for part in (value or "").split(",") if part.strip()}


def plan_changes(
    rows: list[dict[str, str]],
    direction_fit_ids: set[str],
    keep_ids: set[str],
) -> list[tuple[dict[str, str], str]]:
    changes: list[tuple[dict[str, str], str]] = []
    for row in rows:
        creator_id = (row.get("id") or "").strip()
        old_status = (row.get("status") or "").strip()
        if creator_id in keep_ids:
            continue
        if old_status in DEFAULT_LEGACY_STATUSES or (
            old_status == "淘汰" and creator_id in direction_fit_ids
        ):
            changes.append((row, old_status))
    return changes


def write_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument(
        "--direction-fit-ids",
        default="",
        help="Comma-separated IDs currently marked 淘汰 for non-direction reasons",
    )
    parser.add_argument(
        "--keep-ids",
        default="",
        help="Comma-separated IDs to preserve, such as broken or wrong profile links",
    )
    parser.add_argument("--apply", action="store_true", help="Write changes; default is dry-run")
    args = parser.parse_args()

    with args.csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    if not fieldnames or "id" not in fieldnames or "status" not in fieldnames:
        parser.error("CSV must contain id and status columns")

    changes = plan_changes(
        rows,
        direction_fit_ids=parse_ids(args.direction_fit_ids),
        keep_ids=parse_ids(args.keep_ids),
    )
    for row, old_status in changes:
        print(f"{row.get('id')} {old_status or '<blank>'} -> 待触达 | {row.get('name', '')}")

    if args.apply:
        for row, _old_status in changes:
            row["status"] = "待触达"
            notes = (row.get("notes") or "").strip()
            if AUDIT_NOTE not in notes:
                row["notes"] = "｜".join(part for part in (notes, AUDIT_NOTE) if part)
        write_atomic(args.csv_path, fieldnames, rows)
        print(f"applied={len(changes)}")
    else:
        print(f"dry_run={len(changes)}; pass --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
