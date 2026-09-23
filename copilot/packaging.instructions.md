# Packaging & App-Readiness Instructions

## Goals
- Code must be **application-wrappable** and safe to bundle.
- Code must be **import-safe** because it may be imported by other tools.
- Prefer conservative refactors that preserve downstream behavior.

## Import Safety (Hard Rule)
- No heavy work at import time.
- No I/O, CLI parsing, or execution when imported.
- Side effects must live under `main()` or explicit functions.

## Entry Point Pattern
- Provide a `main(argv=None)` function.
- Use `if __name__ == "__main__": raise SystemExit(main())`.

## CLI Conventions
- Always support:
  - `--help`
  - `--debug`
  - `--debug-dir <path>` (required if debug artifacts are created)
  - `--config <path>` (optional, if the tool has multiple parameters)
  - `--output <path>` (preferred name: "output", not "output-dir")
- Prefer `argparse` first.

## Output Conventions
- Prefer **CSV** as the default structured output.
- Avoid JSON unless:
  - DICOM conversion metadata/manifests, or
  - image-related pipelines where JSON meaningfully helps.
- Do not generate PDFs by default.
- Outputs should be:
  - **CSV**: machine-ingestible (and reasonably readable)
  - **Images**: human-readable (labeled, interpretable)

## Refactoring Rules
- When asked to “clean up” code:
  - Preserve **file names and structure** by default.
  - Small reorganizations are allowed only if clearly beneficial.
  - If a change is “major” (file moves, module splits, API changes), **ask first**.

## Backward Compatibility
- Maintain CLI compatibility whenever possible.
- Maintain file formats whenever possible.
- Prefer a clean redesign only if needed, and clearly document the deltas.

## Definition of Done
- Import-safe and app-wrappable.
- CLI is consistent and backwards compatible.
- Output is CSV-first; JSON only when justified.
- Documentation updated alongside code changes.

## Task Prompt (paste into Copilot Chat)
"Refactor to be import-safe and application-ready. Use argparse. Keep filenames/structure unless you must change them (ask first for major changes). Standardize CLI flags: --help, --debug, --debug-dir, optional --config, and prefer --output (not output-dir). CSV-first outputs; JSON only when justified (DICOM/image pipelines). No PDFs."
