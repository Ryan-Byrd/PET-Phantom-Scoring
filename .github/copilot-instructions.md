# GitHub Copilot Instructions (Repository-Wide)

## Core Principles
- When there is a trade-off, prefer **maximum readability** over compactness.
- It is acceptable to **repeat logic** if it improves clarity for future maintenance and review.
- Primary readers are **future me** and **other physicists/scientists**.
- Assume domain knowledge, but **explain the math intent** so a knowledgeable reviewer can agree/disagree with the approach.
- This is **production / regulated** code: changes must be traceable, reviewable, and conservative.

## Refactoring Rules
- Preserve behavior whenever possible; avoid changes that create downstream differences.
- If behavior must change, document exactly what changed and why (briefly).
- Prefer small, incremental refactors over large rewrites.

## Code Style
- Use descriptive names and explicit logic.
- Prefer clarity over cleverness (avoid overly dense expressions).
- Avoid surprising side effects; keep data flow clear.
- Keep modules import-safe (no heavy work at import time unless explicitly intended).

## Comments
- Comments should explain:
  - **why** something is done,
  - **edge cases** and constraints,
  - **algorithmic intent**,
  - **implementation details only when non-obvious**.
- Do **not** remove existing obvious comments automatically (unless specifically asked).

## Documentation Requirements
Documentation should be written **alongside** code changes.

Each module or major feature should include:
- Purpose / scope
- Inputs and outputs (and expected units)
- Assumptions
- Mathematical reasoning (intent only; no derivations)
- Regulatory / standard references when relevant (e.g., NEMA, ACR)

Failure modes:
- Do not emphasize failure modes by default.
- Mention failures only when they are consistent/expected and the reason is useful.

## Math Notes Style
- Explain intent and reasoning; avoid derivations.
- Prefer a dedicated documentation section (e.g., "Math Notes") rather than embedding long math explanations inline everywhere.

## Debugging & Traceability (Global)
- Every script/tool must support a `--debug` CLI flag.
- Debug output must be optional and controlled by flags.
- Debug output should support:
  - plots/images (when applicable),
  - parameter echoes (inputs/config),
  - other artifacts only when helpful for diagnosis.

## Definition of Done (for changes)
- Code is readable and conservative (behavior preserved unless documented).
- Documentation is updated alongside the code.
- Debug flag still works and debug artifacts are generated to the requested directory.
