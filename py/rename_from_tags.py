#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mutagen>=1.47.0",
# ]
# ///

"""Rename audio files in place from embedded tags without moving folders.

Caveat: some BMW collections contain invalid per-track tags where every file in an
album carries the same title. In those cases this script will still rename from the
embedded tags, which can produce misleading repeated filenames that differ only by
track number. The script does not attempt to detect or fix bad source metadata.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3, ID3NoHeaderError
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    MutagenFile = None
    ID3 = None
    ID3NoHeaderError = None


SUPPORTED_EXTENSIONS = {".aac", ".m4a", ".mp3", ".mp4", ".flac", ".wma"}
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WHITESPACE = re.compile(r"\s+")
MAX_FILENAME_BYTES = 255


@dataclass(frozen=True)
class TrackTags:
    track: int
    title: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rename audio files in place from embedded tags."
    )
    parser.add_argument("source", type=Path, help="Directory containing tagged audio files")
    parser.add_argument(
        "--no-subfolders",
        action="store_true",
        help="Do not recurse into subfolders.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned renames without changing files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing destination file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print skipped files as well as renames.",
    )
    return parser.parse_args()


def iter_files(source: Path, recurse: bool) -> list[Path]:
    walker = source.rglob("*") if recurse else source.glob("*")
    return sorted(
        path
        for path in walker
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def first_value(value) -> str | None:
    if value is None:
        return None
    text_attr = getattr(value, "text", None)
    if text_attr is not None:
        if isinstance(text_attr, list):
            if not text_attr:
                return None
            value = text_attr[0]
        else:
            value = text_attr
    elif hasattr(value, "value"):
        value = getattr(value, "value")
    if isinstance(value, list):
        if not value:
            return None
        value = value[0]
    if isinstance(value, tuple):
        if not value:
            return None
        value = value[0]
    text = str(value).strip()
    return text or None


def parse_track_number(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"(\d+)", value)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def sanitize_filename_part(value: str) -> str:
    value = INVALID_FILENAME_CHARS.sub("_", value)
    value = WHITESPACE.sub(" ", value).strip()
    value = value.rstrip(". ")
    return value


def read_tags(path: Path) -> TrackTags | None:
    tags = read_tags_mutagen(path)
    if tags is not None:
        return tags
    return read_tags_ffprobe(path)


def read_tags_mutagen(path: Path) -> TrackTags | None:
    if MutagenFile is None:
        return None

    try:
        audio = MutagenFile(path, easy=True)
    except Exception:
        audio = None
    if audio is not None and audio.tags:
        title = first_value(audio.tags.get("title"))
        track = parse_track_number(first_value(audio.tags.get("tracknumber")))
        if title and track is not None:
            title = sanitize_filename_part(title)
            if title:
                return TrackTags(track=track, title=title)

    try:
        audio = MutagenFile(path)
    except Exception:
        audio = None
    if audio is not None and getattr(audio, "tags", None):
        tags = audio.tags
        title = None
        track = None

        if "\xa9nam" in tags:
            title = first_value(tags.get("\xa9nam"))
        if "trkn" in tags:
            track_value = tags.get("trkn")
            if isinstance(track_value, list) and track_value:
                first_track = track_value[0]
                if isinstance(first_track, tuple) and first_track:
                    track = first_track[0]

        if title is None and "TIT2" in tags:
            title = first_value(tags.get("TIT2"))
        if track is None and "TRCK" in tags:
            track = parse_track_number(first_value(tags.get("TRCK")))

        if title and track is not None:
            title = sanitize_filename_part(title)
            if title:
                return TrackTags(track=track, title=title)

    if ID3 is None:
        return None

    try:
        id3 = ID3(path)
    except (ID3NoHeaderError, OSError):
        return None

    title = first_value(id3.get("TIT2"))
    track = parse_track_number(first_value(id3.get("TRCK")))
    if not title or track is None:
        return None

    title = sanitize_filename_part(title)
    if not title:
        return None

    return TrackTags(track=track, title=title)


def read_tags_ffprobe(path: Path) -> TrackTags | None:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "format_tags=title,track:stream_tags=title,track",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    title = None
    track = None

    format_tags = payload.get("format", {}).get("tags", {})
    title = first_value(format_tags.get("title"))
    track = parse_track_number(first_value(format_tags.get("track")))

    if (not title or track is None) and payload.get("streams"):
        for stream in payload["streams"]:
            stream_tags = stream.get("tags", {})
            if not title:
                title = first_value(stream_tags.get("title"))
            if track is None:
                track = parse_track_number(first_value(stream_tags.get("track")))
            if title and track is not None:
                break

    if not title or track is None:
        return None

    title = sanitize_filename_part(title)
    if not title:
        return None

    return TrackTags(track=track, title=title)


def target_path(path: Path, tags: TrackTags) -> Path:
    return path.with_name(f"{tags.track:02d} - {tags.title}{path.suffix.lower()}")


def filename_too_long(path: Path) -> bool:
    return len(path.name.encode("utf-8")) > MAX_FILENAME_BYTES


def main() -> int:
    args = parse_args()
    source = args.source.expanduser().resolve()
    if not source.is_dir():
        print(f"Source is not a directory: {source}", file=sys.stderr)
        return 2

    files = iter_files(source, recurse=not args.no_subfolders)
    if not files:
        print("No supported audio files found.", file=sys.stderr)
        return 1

    renamed = 0
    skipped = 0
    failed = 0

    for path in files:
        try:
            tags = read_tags(path)
            if tags is None:
                skipped += 1
                if args.verbose:
                    print(f"skip  {path} (missing title/track tags)")
                continue

            dest = target_path(path, tags)
            if dest == path:
                skipped += 1
                if args.verbose:
                    print(f"skip  {path} (already matches)")
                continue

            if filename_too_long(dest):
                skipped += 1
                if args.verbose:
                    print(f"skip  {path} (target filename too long)")
                continue

            if dest.exists() and not args.overwrite:
                skipped += 1
                if args.verbose:
                    print(f"skip  {path} (destination exists: {dest.name})")
                continue

            if args.dry_run:
                print(f"plan  {path} -> {dest}")
            else:
                path.rename(dest)
                print(f"ok    {path} -> {dest}")
            renamed += 1
        except Exception as exc:  # pragma: no cover - operator-facing path
            failed += 1
            print(f"error {path}: {exc}", file=sys.stderr)

    print(f"Done. renamed={renamed} skipped={skipped} failed={failed} source={source}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
