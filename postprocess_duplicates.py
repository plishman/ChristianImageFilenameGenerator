#!/usr/bin/env python3
"""
postprocess_duplicates.py

Scans the target folder for files that already exist with names matching
the *target* names from rename_images.bat.
Then rewrites (or creates) a final batch file with (n) suffixes added
to avoid overwrites from duplicate suggested names.
"""

import argparse
import re
from pathlib import Path

FOLDER = r"./images"                  # ← same as in your main script
BATCH_INPUT = "rename_images.bat"     # the one your main script writes to
BATCH_OUTPUT = "rename_images_final.bat"   # safer: new file so you can compare

def normalize_base(name: str) -> str:
    """Remove extension and any existing (n) suffix for grouping"""
    stem = Path(name).stem
    # remove trailing (123) if present
    stem = re.sub(r'\s*\(\d+\)$', '', stem).strip()
    return stem.lower()


def parse_ren_command(line: str):
    """Parse: ren "source path" target_name"""
    pattern = re.compile(
        r'^\s*ren\s+"(?P<src>[^"]+)"\s+(?P<dst>"[^"]+"|\S+)\s*$',
        re.IGNORECASE,
    )
    match = pattern.match(line)
    if not match:
        return None

    src = match.group('src').strip()
    dst = match.group('dst').strip().strip('"')
    return src, dst

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Post-process rename batch commands to prevent filename collisions by "
            "adding numbered suffixes in execution order."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--folder",
        type=str,
        default=FOLDER,
        help="Folder that contains the images and the input/output batch files.",
    )
    parser.add_argument(
        "--batch-input",
        type=str,
        default=BATCH_INPUT,
        help="Input batch filename to read rename commands from.",
    )
    parser.add_argument(
        "--batch-output",
        type=str,
        default=BATCH_OUTPUT,
        help="Output batch filename to write duplicate-safe rename commands to.",
    )
    args = parser.parse_args()

    root = Path(args.folder).resolve()

    print("Program summary:")
    print("  Reads rename commands from the input batch file.")
    print("  Checks existing filenames and prior commands in execution order.")
    print("  Adds numbered suffixes like '(2)' when a target name already exists.")
    print("  Writes a final safe batch file for review and execution.")
    print("Run settings:")
    print(f"  folder={root}")
    print(f"  batch_input={args.batch_input}")
    print(f"  batch_output={args.batch_output}")

    if not root.is_dir():
        print(f"Folder not found: {root}")
        return

    # 1. Read existing files in the folder (what would be after previous renames)
    current_files = {p.name.lower(): p for p in root.iterdir() if p.is_file()}

    # 2. Read the batch file lines
    batch_path = root / args.batch_input
    if not batch_path.exists():
        print(f"Batch file not found: {batch_path}")
        return

    with open(batch_path, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    # 3. Parse ren commands and keep execution order
    ren_commands = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith('echo') or line.startswith('rem') or line.startswith('@'):
            continue

        parsed = parse_ren_command(line)
        if not parsed:
            continue

        source_path, target_name = parsed
        ren_commands.append((source_path, target_name))

    print(f"Found {len(ren_commands)} rename commands in batch")

    # 4. Resolve duplicate/conflicting targets in-order
    new_lines = []
    existing_names = set(current_files.keys())
    duplicate_counts = {}

    for source_path, desired_target in ren_commands:
        src_name = Path(source_path).name.lower()
        desired_lower = desired_target.lower()
        base_stem = normalize_base(desired_target)
        ext = Path(desired_target).suffix

        # Simulate source being renamed away so it no longer blocks destination checks.
        existing_names.discard(src_name)

        candidate = desired_target
        counter = 1
        while candidate.lower() in existing_names:
            counter += 1
            candidate = f"{base_stem} ({counter}){ext}"

        if candidate.lower() != desired_lower:
            duplicate_counts[base_stem] = duplicate_counts.get(base_stem, 1) + 1

        new_lines.append(f'ren "{source_path}" "{candidate}"\n')
        existing_names.add(candidate.lower())

    for base_stem, count in sorted(duplicate_counts.items()):
        print(f"Duplicate/conflict resolved: {base_stem} ({count} total)")

    # 5. Write the final batch file
    out_path = root / args.batch_output
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("@echo off\n")
        f.write("echo Starting final rename (with duplicate handling)...\n\n")
        f.writelines(new_lines)
        f.write("\necho Done.\npause\n")

    print(f"\nFinal batch file created: {out_path}")
    print("Review it, then run it from cmd in the images folder.")
    print(f"You can compare with original: {batch_path}")

if __name__ == "__main__":
    main()