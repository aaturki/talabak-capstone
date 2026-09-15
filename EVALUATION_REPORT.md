# Evaluation Report — Talabak

Generated at 2026-09-15T21:07:19.075987+00:00 from an actual application run through the SDK to a local simulator.

**This report contains local simulator evidence. No live commercial or open-weight language model was run. External spend is zero.**

## Results

- Golden cases: **144/144**; safety cases: **78/78**.
- Attack block rate: **100.0%** across 40 attacks; false-positive rate: **0.0%** across 40 legitimate requests.
- Clean regression gate: **PASS**; deliberately degraded configuration: **BLOCK**.
- Fault and repair drills: **PASS**.

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

## Evidence for each project section

1. **Architecture:** A Protocol and a single SDK boundary, configuration-based aliases, and retry/fallback behavior exercised under scripted faults.
2. **Structured outputs and tools:** Pydantic validation and gateway schema enforcement, validate/retry/repair, and actual tool loops. The database enforces ownership, policy, and confirmation bound to the specific action.
3. **Guardrails:** Arabic/English normalization, deterministic blocking, and PII masking before model calls and logging, followed by a simulated classifier. Outputs, tool results, and citations are checked.
4. **Evaluation:** 144 original, fixed cases with explicit strata. Evaluation runs the same handle_message entrypoint. The simulated judge tests the interface contract only; human-calibrated κ is unavailable.
5. **Cost:** Observed usage and illustrative tariff estimates are separated from actual spend. BENCHMARKS.md documents the cache experiment with an evaluation verdict for every step.
6. **Model comparison:** Switching simulator configurations was tested. A live model comparison and break-even analysis based on measured throughput remain unavailable.
7. **Operation:** One notebook contains the conversation, tests, and reports, with a setup cell that starts the simulator automatically. Embedded source supports local review; repository cloning and evidence of Run all in Colab await authorized publication.

## Judge and human calibration

Simulated judgments are saved separately for each dimension. Human labels remain blank: no agreement or κ values are fabricated, and an uncalibrated judge does not gate change acceptance. Actual human labeling of live-model outputs is required, followed by calibration against the same output version.

## Limitations and remaining work

- All store and customer data are synthetic. Demo identities are not a production authentication system.
- The dataset was authored during development; it is not an independent test of model intelligence. Its expected outcomes require the project owner's review.
- The Track D simulator is deterministic code inspired by the course gateway contract. It is neither an unmodified Murshid implementation nor a language model.
- Commercial/open-weight model quality, actual provider caching, real operating cost, and LLM hardware throughput have not been established.
- Timing and illustrative cost estimates here describe HTTP requests and simulator rules. They must not be generalized to a live model.
- Cohort dates, signed peer review, an actual Colab run, and GitHub publication/submission remain incomplete. Nothing is published or submitted without the user's request.

## Traceable evidence

- artifacts/report.json and artifacts/primary/results.jsonl: aggregate results and each case's outputs and usage.
- artifacts/open_weight: the same dataset rerun using an alternative simulator configuration.
- artifacts/degraded and artifacts/faults.json: deliberate regression and connection fault drills.
- artifacts/calibration.json and artifacts/human_labels.template.csv: calibration status with no fabricated labels.
- eval/baseline.simulator.json: a saved baseline from a previous successful run; the runner does not update it automatically.
- RUBRIC_EVIDENCE.md: requirements mapped to their sources and the limits of each piece of evidence.
