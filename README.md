# weko3-metadata-registrar

This repository can regenerate WEKO metadata import ZIP files from the current template TSV and source CSV.

## Current input files

- Template TSV: `metadatas\template\ResearchArtifact(40001).tsv`
- Source CSV: `metadatas\watanabe_data\sample.csv`

## Output files

- Schema JSON: `metadatas\config\metadata_schema_40001.json`
- ZIP files: `metadatas\output\zip_data\import_*.zip`

## Commands

Run the following commands from the repository root in PowerShell.

```powershell
Set-Location C:\Users\Koshi\dataeco
```

```powershell
uv run --project metadatas python metadatas\src\scripts\make_template.py `
  --template "metadatas\template\ResearchArtifact(40001).tsv" `
  --output "metadatas\config\metadata_schema_40001.json"
```

```powershell
uv run --project metadatas python metadatas\src\scripts\generate_metadata_imports.py `
  --input "metadatas\watanabe_data\sample.csv" `
  --output-dir "metadatas\output\zip_data" `
  --schema-config "metadatas\config\metadata_schema_40001.json" `
  --chunk-size 50 `
  --zip
```

## Fixed rules used when creating JSON from TSV

The schema JSON is created from the template TSV with the following rules.

- `.IndexID[0]`, `.POS_INDEX[0]`, and `.PUBLISH_STATUS` are read from the first data row in the template TSV.
- `PubDate` is always set to `2025-05-27`.
- `#ID`, `URI`, `.FEEDBACK_MAIL[0]`, `.CNRI`, `.DOI_RA`, and `.DOI` are always set to blank.

If you want to change `.IndexID[0]` or `.POS_INDEX[0]`, update the first data row in `metadatas\template\ResearchArtifact(40001).tsv` before running `make_template.py`.

## Notes

- `uv run --project metadatas ...` uses `metadatas\pyproject.toml`.
- `generate_metadata_imports.py` can omit `--index-id`, `--index-name`, `--publish-date`, and `--publish-status`.
- If they are omitted, the values in `metadata_schema_40001.json` are used.
- `--zip` creates ZIP files and removes intermediate TSV files.
- If you want to keep TSV files as well, use `--zip --keep-tsv`.
- Generated TSV files are written as `UTF-8 with BOM` to match WEKO's import format expectations.
- `selenium_auto_register.py` now moves successfully uploaded ZIP files to `metadatas\output\uploaded_zip_data` by default, so they are not uploaded again on the next run.
- If you want to delete them instead, use `--delete-zip-after-import`. If you want to keep them in place, use `--keep-zip-after-import`.
