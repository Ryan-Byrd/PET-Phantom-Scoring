# Comments & Readability Instructions

## Priority
- Prefer **maximum readability** over compactness.
- Repeating logic is acceptable when it improves clarity.

## Comments: What to Include
Comments should explain:
- Why something is done (design intent)
- Edge cases / constraints
- Algorithmic intent
- Implementation details only when non-obvious

## Comments: What NOT to Do
- Do not remove existing comments automatically (even if obvious), unless explicitly asked.
- Avoid redundant comments that restate code line-by-line in new code you write.

## Function Size & Complexity
- No hard line limit, but avoid unnecessarily long functions.
- Break up functions **only when** logic becomes complex or readability materially improves.
- Prefer small helper functions with clear names when it reduces cognitive load.

## Control Flow & Clarity
- Prefer explicit branches over clever one-liners.
- Prefer named intermediate variables for readability.
- Avoid deeply nested logic when a clearer structure exists.

## Definition of Done
- Code is easy to read and review.
- Comments explain intent and constraints without being noisy.
- Any complex logic has a short “why/how” explanation.

## Task Prompt (paste into Copilot Chat)
"Improve readability first. Do not remove existing comments. Add comments that explain why/edge cases/intent, and only explain implementation details when non-obvious. Split functions only if complexity warrants it."
