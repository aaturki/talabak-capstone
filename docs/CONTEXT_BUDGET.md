# Context budget

## What is bounded, and why

Each model call uses the `max_output_tokens` bound in `config/models.json`. The initial shipped value is 768; measurement reads the current setting. An output limit does not measure total context usage: instructions, data, schemas and tool results also contribute to the request.

Action state lives in `Session` and the store database, outside model instructions. The application retains the last request, pending action and confirmation digest without building unlimited conversation history. Remembering an action depends on explicit session data, not an assumption that the simulator remembers everything said. Tests document confirmation limits and the effects of changing topics or data.

## Measurement method

Run `scripts/context_budget.py` after the source files are ready. It measures:

- Each prompt file using the simulator's `o200k_base` tokenizer.
- The fictional store file and the actual JSON rendered by `tool_definitions()` after loading descriptions and schemas.
- The component inventory sum and configured output bound. JSON/tool envelopes and request construction may contribute additional tokens.

The result is saved to `artifacts/context_budget.json` and displayed in the notebook. Counting files separately measures component size. The actual request's `usage.prompt_tokens` records what reached the simulator. A live model requires its own tokenizer or provider token-counting endpoint; do not reuse a reference project's Arabic/English ratio.

## Evidence limits

The simulator does not establish a live model's context window or prefill latency. No commercial context-window size or overflow rate is claimed without a documented run. This document describes the method; use the generated artifact for current values rather than a manual estimate.
