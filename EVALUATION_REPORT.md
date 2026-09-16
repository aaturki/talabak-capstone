# Evaluation Report — Talabak

Generated at 2026-09-16T17:18:45.533976+00:00 from an actual application run through the SDK to a local simulator.

**The simulator sections below are local evidence with zero external spend; the 'Live model runs' section reports the real-provider comparison recorded under artifacts/live.**

## Results

- Golden cases: **144/144**; safety cases: **78/78**.
- Guard corpora: 52 attacks and 50 legitimate requests (bilingual, development plus held-out splits).
  - Deterministic layer alone: block rate **100.0%**, false-positive rate **0.0%**.
  - End-to-end pipeline (deterministic layer, PII masking, then the classifier; evidence `pipeline:simulator`): block rate **100.0%**, false-positive rate **0.0%**; blocked by layer: {"deterministic": 52}.
- Clean regression gate: **PASS**; deliberately degraded configuration: **BLOCK** (slice table below).
- Fault and repair drills: **PASS**.
- Served prompts: router.v1.md, workflow.v1.md, guard.v3.md, repair.v2.md, context.v1.md.

## Regression gate read by slice

The clean run compares the committed baseline with the current code; the degraded run swaps in `prompts/router.degraded.v0.md` (every request becomes FAQ). Only slices that dropped more than the 2% margin, plus the deterministic safety stop, are listed.

| Slice | Baseline pass rate | Degraded pass rate | Drop |
|---|---:|---:|---:|
| safety | – | – | deterministic_safety_failed_or_missing |
| overall | 1.000 | 0.319 | 0.681 |
| intent=appointment | 1.000 | 0.208 | 0.792 |
| intent=exchange | 1.000 | 0.167 | 0.833 |
| intent=handoff | 1.000 | 0.167 | 0.833 |
| intent=order_status | 1.000 | 0.167 | 0.833 |
| intent=return | 1.000 | 0.208 | 0.792 |
| language=ar | 1.000 | 0.385 | 0.615 |
| language=en | 1.000 | 0.188 | 0.812 |
| difficulty=easy | 1.000 | 0.304 | 0.696 |
| difficulty=hard | 1.000 | 0.897 | 0.103 |
| difficulty=medium | 1.000 | 0.141 | 0.859 |
| risk=high | 1.000 | 0.359 | 0.641 |
| risk=low | 1.000 | 0.621 | 0.379 |
| risk=medium | 1.000 | 0.000 | 1.000 |

## Comparison by stratum

The names below identify two configurations of the same simulator. This is not a quality comparison of two real models.

| Dimension | Stratum | primary passed/total | open_weight simulator passed/total |
|---|---|---:|---:|
| intent | appointment | 24/24 | 24/24 |
| intent | exchange | 24/24 | 24/24 |
| intent | faq | 24/24 | 24/24 |
| intent | handoff | 24/24 | 24/24 |
| intent | order_status | 24/24 | 24/24 |
| intent | return | 24/24 | 24/24 |
| language | ar | 96/96 | 96/96 |
| language | en | 48/48 | 48/48 |
| difficulty | easy | 23/23 | 23/23 |
| difficulty | hard | 29/29 | 29/29 |
| difficulty | medium | 92/92 | 92/92 |
| risk | high | 78/78 | 78/78 |
| risk | low | 29/29 | 29/29 |
| risk | medium | 37/37 | 37/37 |

## Live model runs

Run `20260916T164049Z-004486c95c` (status **LIVE_ERRORS**, 2026-09-16T16:59:25.853635+00:00), same 144 golden cases, response caching and fallbacks disabled, provenance `5e689a0f40df…`. Live evidence flag: **True**.

| Route | Requested model | Served model | Golden passed | Safety passed | Wire calls | Input tokens | Cached input | Estimated cost (USD) | p50 ms | p95 ms |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| primary (live_commercial) | gpt-5-mini | gpt-5-mini-2025-08-07 | 140/144 | 76/78 | 400 | 648441 | 81.6% | 0.0750 | 4641 | 8698 |
| open_weight (live_open_weight) | deepseek-flash | deepseek-flash | 136/144 | 72/78 | 412 | 802310 | 83.2% | 0.1098 | 3145 | 7375 |

Costs use the dated tariffs recorded in the run configuration; they are estimates, not invoices. Cached input is the provider-reported share over responses with known usage.

### Comparison by slice (live)

| Dimension | Stratum | primary passed/total | open_weight passed/total |
|---|---|---:|---:|
| intent | appointment | 23/24 | 21/24 |
| intent | exchange | 24/24 | 21/24 |
| intent | faq | 24/24 | 24/24 |
| intent | handoff | 24/24 | 23/24 |
| intent | order_status | 22/24 | 24/24 |
| intent | return | 23/24 | 23/24 |
| language | ar | 94/96 | 89/96 |
| language | en | 46/48 | 47/48 |
| difficulty | easy | 23/23 | 23/23 |
| difficulty | hard | 27/29 | 29/29 |
| difficulty | medium | 90/92 | 84/92 |
| risk | high | 76/78 | 72/78 |
| risk | low | 28/29 | 29/29 |
| risk | medium | 36/37 | 35/37 |
- primary failed cases: G032, G042, G065, G104.
- open_weight failed cases: G058, G076, G078, G081, G098, G102, G112, G122.
- open_weight operational errors: G098.

### Guard corpora on the live commercial route

Deterministic layer plus the live classifier (`pipeline:live_commercial`): block rate **100.0%** of 52 attacks, false-positive rate **6.0%** of 50 legitimate requests; false positives: L033, L036, L043; blocked by layer: {"deterministic": 52, "null": 2, "classifier": 1}.

### Judge calibration against human labels

Dimension **groundedness**, 40 labelled pairs, agreement **42.5%**, Cohen's κ **-0.020**, status **NOT_CALIBRATED** (gate reasons: kappa_not_established_or_below_threshold).

| human \ judge | PASS | PARTIAL | FAIL |
|---|---:|---:|---:|
| PASS | 17 | 10 | 10 |
| PARTIAL | 0 | 0 | 2 |
| FAIL | 1 | 0 | 0 |

## Evidence for each project section

1. **Architecture:** A Protocol and a single SDK boundary, configuration-based aliases, and retry/fallback behavior exercised under scripted faults.
2. **Structured outputs and tools:** Pydantic validation and gateway schema enforcement, validate/retry/repair, and actual tool loops. The database enforces ownership, policy, and confirmation bound to the specific action.
3. **Guardrails:** Arabic/English normalization, deterministic blocking, and PII masking before model calls and logging, followed by a simulated classifier. Block and false-positive rates are reported for the deterministic layer alone and for the whole pipeline. Outputs, tool results, and citations are checked.
4. **Evaluation:** 144 original, fixed cases with explicit strata. Evaluation runs the same handle_message entrypoint. The simulated judge tests the interface contract only; human-calibrated κ is unavailable.
5. **Cost:** Observed usage and illustrative tariff estimates are separated from actual spend. BENCHMARKS.md documents the cache experiment with an evaluation verdict for every step.
6. **Model comparison:** Switching simulator configurations was tested. A live model comparison and break-even analysis based on measured throughput remain unavailable.
7. **Operation:** One notebook contains the conversation, tests, and reports. Its setup follows the course repository-clone pattern; local review uses the existing checkout. A real repository locator and fresh Colab Run all still require publication and verification.

## Judge and human calibration

Simulated judgments are saved separately for each dimension. Human labels remain blank: no agreement or κ values are fabricated, and an uncalibrated judge does not gate change acceptance. Actual human labeling of live-model outputs is required, followed by calibration against the same output version.

## Limitations and remaining work

- All store and customer data are synthetic. Demo identities are not a production authentication system.
- The dataset was authored during development; it is not an independent test of model intelligence. Its expected outcomes require the project owner's review.
- The Track D simulator is deterministic code inspired by the course gateway contract. It is neither an unmodified Murshid implementation nor a language model.
- Commercial/open-weight model quality, actual provider caching, real operating cost, and LLM hardware throughput have not been established.
- Timing and illustrative cost estimates here describe HTTP requests and simulator rules. They must not be generalized to a live model.
- Signed peer review, an actual Colab run, and GitHub publication/submission remain incomplete. Nothing is published or submitted without the user's request.

## Traceable evidence

- artifacts/report.json and artifacts/primary/results.jsonl: aggregate results and each case's outputs and usage.
- artifacts/open_weight: the same dataset rerun using an alternative simulator configuration.
- artifacts/degraded and artifacts/faults.json: deliberate regression and connection fault drills.
- artifacts/calibration.json and artifacts/human_labels.template.csv: calibration status with no fabricated labels.
- eval/baseline.simulator.json: a saved baseline from a previous successful run; the runner does not update it automatically.
- RUBRIC_EVIDENCE.md: requirements mapped to their sources and the limits of each piece of evidence.
