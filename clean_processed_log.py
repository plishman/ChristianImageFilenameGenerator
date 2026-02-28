#!/usr/bin/env python3
"""
clean_processed_log.py

Removes entries from processed_images.log that do not appear as source paths in
rename_images.bat.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

DEFAULT_FOLDER = "./images"
DEFAULT_BATCH = "rename_images.bat"
DEFAULT_LOG = "processed_images.log"

REN_PATTERN = re.compile(r'^\s*ren\s+"(?P<src>[^"]+)"\s+(?P<dst>"[^"]+"|\S+)\s*$', re.IGNORECASE)


def parse_batch_source_paths(batch_path: Path) -> set[str]:
    source_paths: set[str] = set()

    with open(batch_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = REN_PATTERN.match(line)
            if not match:
                continue

            src = Path(match.group("src").strip())
            source_paths.add(str(src.resolve()).lower())

    return source_paths


def read_log_entries(log_path: Path) -> list[str]:
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        return [line.rstrip("\r\n") for line in handle]


def filter_log_entries(entries: list[str], valid_sources: set[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    removed: list[str] = []

    for raw in entries:
        entry = raw.strip()
        if not entry:
            continue

        normalized = str(Path(entry).resolve()).lower()
        if normalized in valid_sources:
            kept.append(raw)
        else:
            removed.append(raw)

    return kept, removed


def backup_file(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.backup_{timestamp}")
    backup.write_bytes(path.read_bytes())
    return backup


def write_log(log_path: Path, entries: list[str]) -> None:
    with open(log_path, "w", encoding="utf-8", errors="replace", newline="\n") as handle:
        if entries:
            handle.write("\n".join(entries) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove processed_images.log entries not present in rename_images.bat"
    )
    parser.add_argument("--folder", default=DEFAULT_FOLDER, help="Folder containing the files")
    parser.add_argument("--batch", default=DEFAULT_BATCH, help="Batch file name")
    parser.add_argument("--log", default=DEFAULT_LOG, help="Processed log file name")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be removed without writing")
    parser.add_argument("--show-first", type=int, default=20, help="How many removed entries to preview")
    args = parser.parse_args()

    root = Path(args.folder).resolve()
    batch_path = root / args.batch
    log_path = root / args.log

    if not root.is_dir():
        raise SystemExit(f"Folder not found: {root}")
    if not batch_path.exists():
        raise SystemExit(f"Batch file not found: {batch_path}")
    if not log_path.exists():
        raise SystemExit(f"Log file not found: {log_path}")

    valid_sources = parse_batch_source_paths(batch_path)
    log_entries = read_log_entries(log_path)
    kept, removed = filter_log_entries(log_entries, valid_sources)

    print(f"Batch source entries: {len(valid_sources)}")
    print(f"Log entries        : {len([x for x in log_entries if x.strip()])}")
    print(f"Would keep         : {len(kept)}")
    print(f"Would remove       : {len(removed)}")

    preview_count = max(0, args.show_first)
    if removed and preview_count:
        print(f"\nFirst {min(preview_count, len(removed))} entries to remove:")
        for item in removed[:preview_count]:
            print(item)

    if args.dry_run:
        print("\nDry run complete. No files were modified.")
        return

    backup_path = backup_file(log_path)
    write_log(log_path, kept)

    print(f"\nBackup written to: {backup_path}")
    print(f"Updated log file : {log_path}")


if __name__ == "__main__":
    main()
