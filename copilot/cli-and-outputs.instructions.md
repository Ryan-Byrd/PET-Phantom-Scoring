# CLI & Output Conventions

## CLI Flag Names (Standard)
- Prefer:
  - `--output <path>` (not `--output-dir`)
  - `--config <path>` when configuration is non-trivial
  - `--debug` and `--debug-dir <path>`
- Always implement `--help`.
- Use `argparse` unless there is a compelling reason not to.

## Output Formats
- Default structured output: **CSV**
- Avoid JSON unless:
  - DICOM conversion pipeline metadata/manifests, or
  - image pipelines where JSON is genuinely useful
- Do not generate PDFs by default.

## Output Expectations
- CSV: machine-ingestible and reasonably human-readable
- Images: human-readable; include labeling/annotations when it helps interpretation

## Task Prompt (paste into Copilot Chat)
"Standardize CLI to use --output (not output-dir), optional --config, and always support --help/--debug/--debug-dir. Prefer CSV outputs; avoid JSON except for DICOM/image pipelines; do not generate PDFs."
