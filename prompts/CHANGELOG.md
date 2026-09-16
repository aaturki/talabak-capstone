# Prompt history

Every served prompt is a versioned file. The application selects versions explicitly through `config/models.json` (`pipeline.prompt_versions`); it never serves "the newest file on disk". The served version is recorded as a digest in every usage row and as file names in `artifacts/report.json`.

## Model-facing prompts

- router-v1: first retail extraction contract, missing-field preservation.
- router.degraded.v0: deliberately broken router (every request becomes FAQ) used only by the regression-gate demonstration; never served by default.
- workflow-v1: tools, provenance, confirmation boundaries and canary.
- guard-v1: bilingual intent-override detection with legitimate policy-question carve-outs.
- guard-v2 (served since 2026-09-16): adds explicit carve-outs for questions about a technical term, quoted or reported scams and negated statements, after the end-to-end guard evaluation showed the classifier layer refusing three legitimate corpus cases (L013, L035, L036). The simulator ignores prompt wording, so the effect on a real classifier is unmeasured until the live run.
- guard-v3 (served since 2026-09-16, evening): written after the first full live run on gpt-5-mini with guard-v2 blocked 8 of 144 golden requests that carry unknown or malformed order/slot/SKU identifiers, a masked phone number or the words "without a signed-in customer" (G032, G033, G042, G078, G102, G104, G106, G112; six of them safety cases). v3 states that identifiers, own contact details and requests that may later be denied by the application are legitimate, and that uncertainty must not block. Measured again on the same cases after the change (see EVALUATION_REPORT.md live section).
- repair-v1: bounded repair using validation categories; rejected values are not echoed.
- repair-v2 (served since 2026-09-16): states that the rejected response is not repeated and that each error carries type, location and validator message. Rejected values are still never echoed; the message text is category-level and PII-masked.
- tools.v1.json: tool names and descriptions served in every tools-stage request (part of the prompt version digest).
- context.v1.md (served by default since 2026-09-16, ADR-011): shared prefix with public retail facts and tool contracts placed before every stage prompt when `pipeline.stable_context` is true. Private orders and session data are excluded. Its enablement was measured first in the simulator cache benchmark; provider caching is accepted only from returned usage fields.

## Judge prompts

- judge.groundedness.v1: single-dimension groundedness rubric used by the local runner.
- judge.groundedness.v2: candidate revision prepared for the live blinded review; served by `scripts/prepare_review.py` by default and recorded per row by `rubric_sha256`. No improvement is claimed without paired human-labelled runs.
- judge.completeness.v1: single-dimension completeness rubric.

These are original project prompts. No improvement is claimed without paired runs.
