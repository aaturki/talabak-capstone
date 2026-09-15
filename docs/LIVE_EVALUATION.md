# Live evaluation and human calibration

## Current evidence

The live workflow is prepared but has not been run against a commercial model or a real open-weight model. No provider, key, or live price is selected by these scripts. Implementation tests use an injected local HTTP fixture and remain `TEST_ONLY`; they are not model-quality, spend, or human-calibration results.

The default application and `scripts/run_all.py` continue to use the simulator. Live artifacts are written separately under `artifacts/live/<unique-run-id>/`. A successful deterministic evaluation does not by itself establish live model evidence or a calibrated judge.

## 1. Select configuration later

Copy `config/models.live.example.json` to a private, user-selected configuration path. Fill the exact endpoint, requested model, explicit capabilities and named authentication source for `primary` (commercial) and `open_weight`. Authentication identifies an environment variable or secret-store entry; never put a key value in JSON. Select a `judge` route separately when ready to run it.

`preflight(config)` validates configuration without reading environment variables or secrets, creating a client, or calling a provider. It lists missing fields, route classes, required capabilities, named credentials and the effective budget. Readiness does not prove that a key works or that an endpoint actually supports its declared capabilities. The commercial/open-weight classification is operator supplied; model identity reported by an endpoint is not independently attested.

```python
import json
from pathlib import Path
from scripts.live_evaluate import preflight, run_live_comparison

config = json.loads(Path(LIVE_CONFIG_PATH).read_text("utf-8"))
readiness = preflight(config)
```

Keep the notebook's `RUN_LIVE = False` until a provider, model and credentials are selected and a budget is accepted. A disabled call creates only a `NOT_RUN` manifest and never creates a client or loads secrets. Colab secret loading belongs inside the explicitly enabled branch. An authentication entry of `{"type": "secret", "name": "SELECTED_NAME"}` uses the supplied `secret_loader(name)` callback; `env` reads only its explicitly named variable after enablement.

## 2. Compare the same complete application

```python
if RUN_LIVE:
    run = run_live_comparison(
        config, enabled=True, max_calls=2000,
        out=Path("artifacts/live"),
        # secret_loader=your_explicit_secret_loader,
    )
```

The runner calls `scripts.evaluate.evaluate`, which creates the real `Application`, isolated store and session for each case. It executes every user turn through input checks, schema extraction, model tool proposals, validated domain operations, confirmation and output checks. It uses all 144 authored cases by default, in identical order for both routes, with response caching and model fallbacks disabled. Source expectations are never rewritten. A `max_cases` limit creates an explicitly labelled prefix pilot; it cannot claim full-stratum coverage.

`max_calls` is a shared wire-attempt budget across both routes. It is capped by a smaller configured `settings.budget.max_calls`. Retries count against it; the first route can consume the available budget, in which case incomplete comparison is explicit. A monetary cap additionally requires the adapter's complete tariff and input allowance configuration. A nonretryable provider rejection stops that route. No automatic attempt is made to repair credentials or switch providers.

Each run contains:

| File | Contents |
| --- | --- |
| `manifest.json` | Run status, configuration readiness, source/config/data hashes, selected IDs and traffic hash, route identity checks, total wire meter and limitations |
| `primary.results.jsonl`, `open_weight.results.jsonl` | Actual safe questions, answers, evidence, turn results, tool traces, expected-check outcomes, answer hashes and provenance bindings |
| `primary.summary.json`, `open_weight.summary.json` | Overall and intent/language/difficulty/risk results, safety checks, returned-response metrics and independent wire-attempt metrics |
| `wire_events.json` | Safe response/error metadata and usage for all wire attempts, including rejected or incomplete responses; no request headers or credential values |

`overall` meters returned application usage. `wire_meter` is the cost/accounting view that also includes error attempts. Its totals become `null` if any attempt omits that metric. `usage_coverage` reports known, unknown and known-total counts; known totals are not silently presented as complete totals. A retry error without a model response preserves unknown billable usage but does not count as an unidentified served model; malformed received responses do count. Live `cost_usd` remains `null` because no invoice is verified. `estimated_cost_usd` uses an explicitly supplied tariff and stays separate from actual charges. Missing cache-token data never become zero cache tokens.

Operational statuses include `NOT_RUN`, `NOT_CONFIGURED`, `PARTIAL_BUDGET`, `PARTIAL`, `TEST_ONLY`, `LIVE_ERRORS`, `MODEL_IDENTITY_UNVERIFIED`, `PILOT_COMPLETE`, `LIVE_COMPLETE` and `ERROR`. `LIVE_COMPLETE` means the full comparison completed with identifiable live route evidence; consult `deterministic_verdict` and safety results for quality. A blocked turn with no model call is `deterministic_no_model_call`. Known, distinct served models and matching configured evidence modes are required for `live_model_evidence`. An injected transport cannot meet this condition.

CLI:

```text
python scripts/live_evaluate.py --config <selected-config.json>
python scripts/live_evaluate.py --config <selected-config.json> --enable-live --max-calls 2000
```

The first command records disabled readiness. The enabled CLI exits unsuccessfully for an incomplete, invalid or nonlive comparison.

## 3. Export a genuinely blank human review

```python
from scripts.prepare_review import prepare_review

review = prepare_review(
    Path(run["run_dir"]), Path(run["run_dir"]) / "review-groundedness-v2",
    limit=40,
)
```

The export uses actual stored answers, their trusted evidence and a frozen single-dimension rubric. It checks artifact hashes before export and refuses test/simulator data by default. Exact repeated question/evidence/answer tuples across routes count once. Round-robin sampling covers the available language, intent, difficulty and risk groups; coverage counts describe the actual sample. A 40-row sample does not establish per-stratum calibration.

`human.csv` contains immutable question/evidence/answer and hash fields. The only editable columns are `human_label`, `rater_id`, `annotated_at` and `rationale`, all initially empty. Reviewers read `rubric.md` and assign `PASS`, `PARTIAL` or `FAIL` to that dimension only, add their own rater ID and an ISO date/time, and may explain the decision. Model names, route aliases and reference labels are withheld from the sheet. The manifest records the run and rubric binding. Files are never overwritten in a nonempty review directory.

`allow_non_live=True` exists only for explicit implementation tests. It records `source_is_live=False` permanently and cannot establish live calibration.

## 4. Run the judge separately, then calculate agreement

```python
from scripts.prepare_review import judge_review, score_review
from talabak.llm import SDKClient

if RUN_JUDGE:
    # Supply a separately selected, budgeted judge configuration.
    with SDKClient(config=judge_config, allow_live=True,
                   secret_loader=your_explicit_secret_loader) as client:
        judge = judge_review(review_dir, client, enabled=True,
                             alias="judge", max_calls=100)

# Only after reviewers have supplied their own labels:
calibration = score_review(review_dir, labels_path)
```

The judge sees only the frozen rubric, question, trusted evidence and actual candidate answer. It does not see case IDs, route aliases, model names, deterministic expectations or human labels. It scores exactly one dimension: groundedness or completeness. Judge execution writes `predictions.jsonl` and `judge_manifest.json`; it does not create human labels and refuses to overwrite earlier predictions. The local cap conservatively reserves the configured worst-case retry/fallback attempts before each item. Exactly one known served model must be identified across all received judge responses and predictions. Unknown or mixed identities yield `JUDGE_IDENTITY_UNVERIFIED` and prevent calibration, even if human/judge agreement is perfect.

`score_review` validates unique IDs, answer/evidence hashes, original source artifacts, rubric version and prediction provenance. It rejects edited answers, duplicated rows and stale predictions. `calibration.json` contains agreement, Cohen's kappa, a confusion matrix, disagreements and coverage counts. It reports `NOT_CALIBRATED` until there are at least 40 valid unique pairs, complete selected-sample annotation/prediction coverage, verified live answers and judge evidence, unchanged application source, and kappa at least 0.6. Kappa remains undefined when no pairs exist or both sets contain only one category. These are explicit readiness criteria, not reported achievements.

Rater identities and label origin are self-reported: code cannot prove a person supplied a label. Calibration applies only to this frozen run, source version, sample and rubric; it does not establish general model validity. Changing source or rubric requires a new evaluation/review for a current quality gate. Safety and authorization gates remain deterministic and do not depend on judge scores.

The authored golden cases were used during development and remain exploratory; no independent blind-test claim is made.
