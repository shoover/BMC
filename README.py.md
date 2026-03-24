# BMC Python CLI

`py/bmc_cli.py` is a small command-line port of the core conversion logic from the
original `BMC` WPF project. This Python CLI reuses the same conversion rules and
folder traversal behavior without depending on the original desktop app stack.

Caveat: tested on a single collection bm25 -> AAC conversion.

## Run a smoke test

```bash
python3 py/bmc_cli.py ./BMWData/Music --output ./converted-sample --limit 3 --verbose
```

## Convert the full export

```bash
python3 py/bmc_cli.py ./BMWData/Music --output ./converted-full
```

## Rewrite filenames from tags

```bash
uv run py/rename_from_tags.py ./converted-full --dry-run
uv run py/rename_from_tags.py ./converted-full
```

## Notes

- Default head unit is `NBT`.
- Converted files preserve the source folder structure under the output directory.
- Existing output files are skipped unless `--overwrite` is passed.
- `--next-to-source` writes converted files next to the original `BR*` files.
- `py/rename_from_tags.py` only rewrites filenames in place. Folder names are preserved.
- Files with missing or unusable tags are left unchanged.
- Some collections contain invalid embedded tags where every track in an album has the
  same title. In those cases `py/rename_from_tags.py` can produce misleading repeated
  filenames that differ only by track number.

## How It Works

BMW `BR*` media files are not normal containers. For the formats supported by `BMC`,
the payload is usually the original media bytes with a simple bytewise inversion rule
applied.

The CLI mirrors the rules in `MediaConverter.cs`:

- `br25` and `br4` map to `aac` and `mp3`.
  For `NBT`, every byte is inverted except the last 3 bytes.
  For `CIC`, all bytes are inverted.
- `br28` and `br30` invert every byte except the last byte.
- `br29`, `br34`, and `br48` invert only the first 128 KiB.
- All other supported `BR*` types invert every byte.

The script does not transcode audio. It reconstructs the original file bytes and writes
them back out with the expected standard extension such as `aac`, `mp3`, `m4a`, `wma`,
`mp4`, `flac`, `jpg`, or `m3u`.

Use `--head-unit CIC` when converting files from CIC-based systems.
