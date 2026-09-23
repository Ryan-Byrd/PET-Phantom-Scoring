# Debug & Artifact Instructions

## Global Requirement
Every script/tool must support a CLI flag:
- `--debug` (enables debug behavior)

## Debug Output Directory
- Debug artifacts must be written to a **user-specified directory** via:
  - `--debug-dir <path>` (required when debug artifacts are created)
- Rationale: tools may be wrapped into an application; users must be able to send debug bundles.

## Debug Contents (when applicable)
When `--debug` is enabled, include:
- Parameter echo (inputs, configuration, key derived values)
- Plots/images that clarify intermediate steps (saved to debug dir)

Keep stdout readable; prefer saving artifacts rather than spamming terminal output.

## Auto-Clean Policy
When `--debug` is enabled:
- Support a cleanup behavior that prevents debug directories from growing without bound.
- Preferred approach:
  - `--debug-clean` (default ON unless explicitly disabled)
  - Deletes or rotates old artifacts in the debug directory while keeping the most recent run
- If a run ID or timestamp folder is used, cleanup should keep the latest N runs (e.g., 3–5).

## Artifact Naming
- Use deterministic names when possible (to simplify comparisons).
- If multiple runs are expected, place artifacts under a run folder:
  - `<debug_dir>/<run_id>/...`
- Include a small summary file:
  - `debug_summary.txt` (inputs, version/hash if available, run timestamp, outputs)

## Task Prompt (paste into Copilot Chat)
"Add `--debug` and `--debug-dir` support. When debug is enabled, write parameter echoes and any helpful plots/images to the debug directory. Implement auto-clean (keep only the most recent runs) so debug output doesn’t accumulate."
