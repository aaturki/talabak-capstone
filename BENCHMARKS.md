# BENCHMARKS — simulator evidence only

Generated: 2026-09-15T22:30:16.208561+00:00

These are measured loopback request times and tokenizer counts. Configured tariffs are illustrative assumptions; actual external API spend is $0. No model-performance or commercial-pricing claim is made.

| Route | Cases passed | p50 ms | p95 ms | Input tokens | Cached input | Actual spend | Illustrative tariff estimate |
|---|---:|---:|---:|---:|---:|---:|---:|
| primary (simulator) | 144/144 | 11.31 | 33.76 | 334627 | 0.0% | $0 | $0.407215 |
| open_weight (simulator) | 144/144 | 10.71 | 29.00 | 334781 | 0.0% | $0 | $0.040759 |

## Response-cache experiment

See artifacts/cache_benchmark.json for the fixed workload, before/after measurements and evaluation verdict attached to each step. Semantic-cache representation is a conservative local concept vector, not a learned multilingual embedding model.

```json
{
  "status": "PASS",
  "created_at_utc": "2026-09-15T22:30:15.990968+00:00",
  "traffic_sha256": "54fb4d252ce2ec931f0b53cf2e7ec275c1479956ce095abab6de983f4dcd9853",
  "workload": "Exactly four passes of all first-turn successful read-only FAQ/status golden cases. Deliberately repetitive synthetic workload, not measured store traffic.",
  "semantic_ready": true,
  "selected_threshold": 1.0,
  "steps": [
    {
      "mode": "baseline",
      "requests": 124,
      "passed": 124,
      "model_calls": 336,
      "response_cache_hits": 0,
      "exact_hits": 0,
      "semantic_hits": 0,
      "input_tokens": 170376,
      "output_tokens": 8612,
      "provider_cached_tokens": 0,
      "provider_cache_fraction": 0.0,
      "cost_usd": 0.0,
      "simulated_cost_usd": 0.204824,
      "wall_ms": 966.1038999911398,
      "request_latency_ms_p50": 5.79380000999663,
      "request_latency_ms_p95": 11.126500001410022,
      "failed_ids": [],
      "evidence_mode": "simulator",
      "semantic_threshold": null,
      "golden_overall": {
        "n": 144,
        "passed": 144,
        "pass_rate": 1.0,
        "latency_ms_p50": 11.637399991741404,
        "latency_ms_p95": 32.20109999529086,
        "model_calls": 502,
        "input_tokens": 334641,
        "output_tokens": 18154,
        "cached_tokens": 0,
        "cost_usd": 0.0,
        "simulated_cost_usd": 0.407257,
        "estimated_cost_usd": null,
        "usage_coverage": {
          "input_tokens": {
            "known": 502,
            "unknown": 0,
            "known_total": 334641
          },
          "output_tokens": {
            "known": 502,
            "unknown": 0,
            "known_total": 18154
          },
          "cached_tokens": {
            "known": 502,
            "unknown": 0,
            "known_total": 0
          },
          "cost_usd": {
            "known": 502,
            "unknown": 0,
            "known_total": 0.0
          },
          "simulated_cost_usd": {
            "known": 502,
            "unknown": 0,
            "known_total": 0.407257
          },
          "estimated_cost_usd": {
            "known": 0,
            "unknown": 502,
            "known_total": 0
          }
        }
      },
      "golden_safety": {
        "n": 78,
        "passed": 78,
        "failed": 0,
        "pass_rate": 1.0
      },
      "regression_gate": {
        "status": "PASS",
        "max_drop": 0.02,
        "failures": [],
        "basis": "authored deterministic expectations; no uncalibrated judge"
      }
    },
    {
      "mode": "exact",
      "requests": 124,
      "passed": 124,
      "model_calls": 84,
      "response_cache_hits": 93,
      "exact_hits": 93,
      "semantic_hits": 0,
      "input_tokens": 42594,
      "output_tokens": 2153,
      "provider_cached_tokens": 0,
      "provider_cache_fraction": 0.0,
      "cost_usd": 0.0,
      "simulated_cost_usd": 0.051206,
      "wall_ms": 341.9131000118796,
      "request_latency_ms_p50": 0.7282999868039042,
      "request_latency_ms_p95": 10.97719999961555,
      "failed_ids": [],
      "evidence_mode": "simulator",
      "semantic_threshold": null,
      "golden_overall": {
        "n": 144,
        "passed": 144,
        "pass_rate": 1.0,
        "latency_ms_p50": 11.161999995238148,
        "latency_ms_p95": 29.69409999786876,
        "model_calls": 502,
        "input_tokens": 334643,
        "output_tokens": 18155,
        "cached_tokens": 0,
        "cost_usd": 0.0,
        "simulated_cost_usd": 0.407263,
        "estimated_cost_usd": null,
        "usage_coverage": {
          "input_tokens": {
            "known": 502,
            "unknown": 0,
            "known_total": 334643
          },
          "output_tokens": {
            "known": 502,
            "unknown": 0,
            "known_total": 18155
          },
          "cached_tokens": {
            "known": 502,
            "unknown": 0,
            "known_total": 0
          },
          "cost_usd": {
            "known": 502,
            "unknown": 0,
            "known_total": 0.0
          },
          "simulated_cost_usd": {
            "known": 502,
            "unknown": 0,
            "known_total": 0.407263
          },
          "estimated_cost_usd": {
            "known": 0,
            "unknown": 502,
            "known_total": 0
          }
        }
      },
      "golden_safety": {
        "n": 78,
        "passed": 78,
        "failed": 0,
        "pass_rate": 1.0
      },
      "regression_gate": {
        "status": "PASS",
        "max_drop": 0.02,
        "failures": [],
        "basis": "authored deterministic expectations; no uncalibrated judge"
      },
      "simulated_cost_reduction_vs_baseline": 0.75,
      "actual_cost_reduction_vs_baseline": null,
      "actual_cost_reduction_reason": "Actual spend is zero in both modes; a percentage is undefined"
    },
    {
      "mode": "semantic",
      "requests": 124,
      "passed": 124,
      "model_calls": 86,
      "response_cache_hits": 94,
      "exact_hits": 90,
      "semantic_hits": 4,
      "input_tokens": 42793,
      "output_tokens": 2145,
      "provider_cached_tokens": 0,
      "provider_cache_fraction": 0.0,
      "cost_usd": 0.0,
      "simulated_cost_usd": 0.051373,
      "wall_ms": 374.70490000850987,
      "request_latency_ms_p50": 0.7424999930663034,
      "request_latency_ms_p95": 11.95719999668654,
      "failed_ids": [],
      "evidence_mode": "simulator",
      "semantic_threshold": 1.0,
      "golden_overall": {
        "n": 144,
        "passed": 144,
        "pass_rate": 1.0,
        "latency_ms_p50": 11.191799989319406,
        "latency_ms_p95": 29.644499998539686,
        "model_calls": 502,
        "input_tokens": 334631,
        "output_tokens": 18149,
        "cached_tokens": 0,
        "cost_usd": 0.0,
        "simulated_cost_usd": 0.407227,
        "estimated_cost_usd": null,
        "usage_coverage": {
          "input_tokens": {
            "known": 502,
            "unknown": 0,
            "known_total": 334631
          },
          "output_tokens": {
            "known": 502,
            "unknown": 0,
            "known_total": 18149
          },
          "cached_tokens": {
            "known": 502,
            "unknown": 0,
            "known_total": 0
          },
          "cost_usd": {
            "known": 502,
            "unknown": 0,
            "known_total": 0.0
          },
          "simulated_cost_usd": {
            "known": 502,
            "unknown": 0,
            "known_total": 0.407227
          },
          "estimated_cost_usd": {
            "known": 0,
            "unknown": 502,
            "known_total": 0
          }
        }
      },
      "golden_safety": {
        "n": 78,
        "passed": 78,
        "failed": 0,
        "pass_rate": 1.0
      },
      "regression_gate": {
        "status": "PASS",
        "max_drop": 0.02,
        "failures": [],
        "basis": "authored deterministic expectations; no uncalibrated judge"
      },
      "simulated_cost_reduction_vs_baseline": 0.7491846658594696,
      "actual_cost_reduction_vs_baseline": null,
      "actual_cost_reduction_reason": "Actual spend is zero in both modes; a percentage is undefined"
    }
  ],
  "limitations": [
    "All model routes are deterministic simulators. Their tariffs are illustrative.",
    "Actual cost is zero; no paid-provider cost saving is demonstrated.",
    "Provider prompt-cache tokens, if any, are separate from application response-cache hits.",
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

## Unmet full-mark targets

The application prompt prefixes may remain below the simulator's cache threshold, yielding zero cached input tokens. The >=65% target is not claimed merely because a cache telemetry unit test passes. A saving on the deliberately repetitive cache replay is not a saving measured on production traffic.
