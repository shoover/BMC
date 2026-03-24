#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///

"""Minimal cross-platform CLI for the BMC conversion core."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys


IDRIVE_TO_MEDIA = {
    "br1": "aac",
    "br25": "aac",
    "br27": "mp4",
    "br28": "mp3",
    "br29": "wma",
    "br3": "m4a",
    "br30": "m3u",
    "br34": "mp4",
    "br48": "flac",
    "br4": "mp3",
    "br5": "wma",
    "br67": "jpg",
}

INVERT_FIRST_128K = {"br29", "br34", "br48"}
NBT_SKIP_LAST_3 = {"br25", "br4"}
SKIP_LAST_1 = {"br28", "br30"}


@dataclass(frozen=True)
class Item:
    source: Path
    relative_parent: Path
    stem: str
    extension: str

    @property
    def output_name(self) -> str:
        return f"{self.stem}.{IDRIVE_TO_MEDIA[self.extension]}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert BMW iDrive BR* files using BMC's conversion rules."
    )
    parser.add_argument("source", type=Path, help="Source directory containing BR* files")
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination directory. Defaults to SOURCE-converted unless --next-to-source is used.",
    )
    parser.add_argument(
        "--head-unit",
        choices=("NBT", "CIC"),
        default="NBT",
        help="Head unit type.",
    )
    parser.add_argument(
        "--next-to-source",
        action="store_true",
        help="Write converted files alongside the source BR* files.",
    )
    parser.add_argument(
        "--no-subfolders",
        action="store_true",
        help="Do not recurse into subfolders.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Convert at most N files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing converted files.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each converted file.",
    )
    return parser.parse_args()


def iter_items(source: Path, recurse: bool) -> list[Item]:
    walker = source.rglob("*") if recurse else source.glob("*")
    items: list[Item] = []
    for path in walker:
        if not path.is_file():
            continue
        extension = path.suffix.lower().lstrip(".")
        if extension not in IDRIVE_TO_MEDIA:
            continue
        items.append(
            Item(
                source=path,
                relative_parent=path.parent.relative_to(source),
                stem=path.stem,
                extension=extension,
            )
        )
    return sorted(items, key=lambda item: str(item.source))


def convert_bytes(data: bytes, extension: str, head_unit: str) -> bytes:
    out = bytearray(len(data))
    last_index = len(data) - 1
    for index, value in enumerate(data):
        if extension in INVERT_FIRST_128K:
            out[index] = (~value) & 0xFF if index < 0x20000 else value
        elif extension in NBT_SKIP_LAST_3:
            if last_index - index >= 3:
                out[index] = (~value) & 0xFF
            elif head_unit == "NBT":
                out[index] = value
            else:
                out[index] = (~value) & 0xFF
        elif extension in SKIP_LAST_1:
            out[index] = (~value) & 0xFF if last_index - index >= 1 else value
        else:
            out[index] = (~value) & 0xFF
    return bytes(out)


def destination_for(item: Item, output_root: Path | None, next_to_source: bool) -> Path:
    if next_to_source:
        return item.source.with_name(item.output_name)
    assert output_root is not None
    return output_root / item.relative_parent / item.output_name


def main() -> int:
    args = parse_args()
    source = args.source.expanduser().resolve()
    if not source.is_dir():
        print(f"Source is not a directory: {source}", file=sys.stderr)
        return 2

    output = None
    if not args.next_to_source:
        output = (args.output or source.with_name(f"{source.name}-converted")).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)

    items = iter_items(source, recurse=not args.no_subfolders)
    if args.limit > 0:
        items = items[: args.limit]

    if not items:
        print("No BR* files found.", file=sys.stderr)
        return 1

    converted = 0
    skipped = 0
    failures = 0

    for item in items:
        dest = destination_for(item, output, args.next_to_source)
        if dest.exists() and not args.overwrite:
            skipped += 1
            if args.verbose:
                print(f"skip  {item.source} -> {dest}")
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            converted_bytes = convert_bytes(item.source.read_bytes(), item.extension, args.head_unit)
            dest.write_bytes(converted_bytes)
            converted += 1
            if args.verbose:
                print(f"ok    {item.source} -> {dest}")
        except Exception as exc:  # pragma: no cover - operator-facing path
            failures += 1
            print(f"error {item.source}: {exc}", file=sys.stderr)

    print(
        f"Done. converted={converted} skipped={skipped} failed={failures} "
        f"head_unit={args.head_unit} source={source}"
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
