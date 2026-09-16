# BENCHMARKS — simulator evidence only

Generated: 2026-09-16T14:20:19.037623+00:00

These are measured loopback request times and tokenizer counts. Configured tariffs are illustrative assumptions; actual external API spend is $0. No model-performance or commercial-pricing claim is made.

| Route | Cases passed | p50 ms | p95 ms | Input tokens | Cached input | Actual spend | Illustrative tariff estimate |
|---|---:|---:|---:|---:|---:|---:|---:|
| primary (simulator) | 144/144 | 17.95 | 32.13 | 725817 | 96.3% | $0 | $0.259711 |
| open_weight (simulator) | 144/144 | 18.00 | 31.23 | 725771 | 96.3% | $0 | $0.025955 |

## Prompt-cache and response-cache steps

Each step reruns the full golden set and carries its own gate verdict. `stable_public_context` moves the public policy, catalogue, hours and tool contracts into a fixed prefix so the provider's prefix cache can hit; response caching is disabled in that step so the cached-token share comes only from the provider usage field. Later steps keep the prefix and add the application's exact and semantic response caches.

| Step | Model calls | Provider cached input | Illustrative USD | Reduction vs baseline | Golden | Safety | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| baseline | 336 | 0.0% | $0.208984 | – | 144/144 | 78/78 | PASS |
| stable_public_context | 336 | 96.3% | $0.194998 | 6.7% | 144/144 | 78/78 | PASS |
| exact | 84 | 97.2% | $0.047789 | 77.1% | 144/144 | 78/78 | PASS |
| semantic | 86 | 97.2% | $0.048503 | 76.8% | 144/144 | 78/78 | PASS |

Pipeline default `stable_context` at run time: **True**. Targets measured on the simulator (simulator usage.prompt_tokens_details.cached_tokens over a 1024-token minimum prefix and illustrative tariffs; a live provider must confirm both targets):

- `provider_input_cache_at_least_65_percent`: **met**
- `simulated_cost_reduction_at_least_60_percent`: **met**
- `every_step_quality_passed`: **met**
- `zero_semantic_wrong_hits`: **met**

## Response-cache experiment

See artifacts/cache_benchmark.json for the fixed workload, before/after measurements and evaluation verdict attached to each step. The semantic tier is a deterministic lexical concept map with nearly binary scores; its threshold sweep has no real operating point and the tier stays disabled by default (ADR-008).

```json
{
  "status": "PASS",
  "created_at_utc": "2026-09-16T14:20:18.822464+00:00",
  "traffic_sha256": "54fb4d252ce2ec931f0b53cf2e7ec275c1479956ce095abab6de983f4dcd9853",
  "workload": "Exactly four passes of all first-turn successful read-only FAQ/status golden cases. Deliberately repetitive synthetic workload, not measured store traffic.",
  "semantic_ready": true,
  "selected_threshold": 1.0,
  "provider_input_cache_fraction": 0.9630977922347568,
  "simulated_cost_reduction": 0.7679104620449413,
  "targets": {
    "provider_input_cache_at_least_65_percent": true,
    "simulated_cost_reduction_at_least_60_percent": true,
    "every_step_quality_passed": true,
    "zero_semantic_wrong_hits": true
  },
  "targets_basis": "simulator usage.prompt_tokens_details.cached_tokens over a 1024-token minimum prefix and illustrative tariffs; a live provider must confirm both targets",
  "pipeline_default_stable_context": true,
  "limitations": [
    "All model routes are deterministic simulators. Their tariffs are illustrative.",
    "Actual cost is zero; no paid-provider cost saving is demonstrated.",
    "Provider prompt-cache tokens are measured in the stable_public_context step with response caching disabled; response-cache hits are a separate mechanism.",
    "The shared prefix adds public context to every call, so its per-call token count is higher than the baseline; the saving comes from the cached share and from response-cache skips.",
    "A new full 144-case golden evaluation accompanies each step.",
    "Near misses and heldout pairs test this limited concept map; results do not establish embedding-model accuracy.",
    "Repeated holdout checks after the first are regression checks; thresholds must not be retuned to them."
  ]
}
```

## Structured validation by language

The report below counts actual validation attempts and first-pass outcomes, including failures; a schema's existence is not a pass rate.

```json
{
  "ar": {
    "attempts": 77,
    "first_attempts": 77,
    "first_pass": 77,
    "final_valid": 77
  },
  "en": {
    "attempts": 51,
    "first_attempts": 51,
    "first_pass": 51,
    "final_valid": 51
  }
}
```

## Self-host break-even

Not computed: no real LLM throughput measured, no hardware cost supplied, and no live commercial bill. Do not derive LLM throughput from these HTTP simulator latencies. Both commercial-versus-self-host and gateway/open-weight-versus-self-host comparisons require actual inputs before calculating a number.

## Full-mark targets and their evidence boundary

The >=65% cached-input and >=60% cost-reduction targets are met on the simulator's usage fields and illustrative tariffs (table above).
Simulator usage fields prove the prefix layout and accounting, not a provider's cache policy or price; the live cache measurement (`scripts/live_benchmark.py`) is the final proof. A saving on the deliberately repetitive cache replay is not a saving measured on production traffic.
