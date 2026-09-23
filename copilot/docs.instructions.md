# Documentation Instructions

## Goal
Write documentation alongside code changes so a domain expert can review the intent, math choices, and standards alignment.

## Required Documentation Elements
Include (as appropriate):
- Purpose / scope of the module or feature
- Inputs and outputs
- Units (explicitly)
- Assumptions / constraints
- Mathematical reasoning (intent and justification; **no derivations**)
- Regulatory / standards references when relevant (e.g., NEMA, ACR)

Failure modes:
- Generally avoid a dedicated failure-modes section.
- Mention a failure only when it is consistent/expected and the reason helps diagnosis or review.

## Math Notes Section
Prefer a dedicated section titled **"Math Notes"** that includes:
- What is being computed and why
- Definitions of symbols/variables used
- Any thresholds/heuristics and why they were chosen
- Units and expected ranges
- Links to standard sections when applicable

## Placement Guidance
- For a module: put "Purpose" and "Math Notes" in the module header docstring.
- For a function: keep docstrings concise; point to "Math Notes" if detailed explanation exists.

## Task Prompt (paste into Copilot Chat)
"Update the code and update documentation alongside it. Include purpose, inputs/outputs, units, assumptions, math intent (no derivations), and relevant NEMA/ACR references. Keep failure-mode discussion minimal."
