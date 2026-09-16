# Live cost, cache and self-host measurements

These functions are optional notebook experiments. Their default is `enabled=False`, which makes no client, reads no credential and performs no inference. Choose providers, models, runtime and spending limits before enabling them.

## Cache and cost

`scripts.live_benchmark.measure_cache(config, enabled=True, out=...)` runs the actual application in four phases:

1. Current prompt arrangement, response cache disabled.
2. A stable prefix of useful public store facts and tool contracts, response cache disabled.
3. The same context with exact response caching.
4. The same context with the measured semantic threshold, only if held-out near misses have zero wrong hits.

Every phase uses the same frozen, explicitly repetitive synthetic workload and is followed by a full golden evaluation. The summary retains the safety result and regression verdict for every phase. No expectation or baseline is rewritten to turn a failure into a pass.

The prefix is `prompts/context.v1.md` plus public catalogue, policy and hours data. Orders, customer records and session identity are excluded. It supplies useful context rather than meaningless padding. Since 2026-09-16 it is the pipeline default (`pipeline.stable_context: true`, ADR-011) after the simulator cache benchmark measured it with a full golden evaluation per step; the live measurement still compares baseline and prefix phases so a real model's behaviour and a real provider's cache policy decide whether the default stays.

Provider caching is read from the response's usage fields in the second phase, while response caching is disabled. Missing usage is unknown; a reported zero is zero. When a retried or errored attempt has unknown usage, the cached share is reported over the known responses with the number of excluded attempts (`provider_cache_fraction_basis: known_responses_only`). The target is at least 65% cached input tokens. Savings use supplied dated tariffs and observed token counts, with a target of at least 60%; they are estimates, not provider invoices. Existing provider cache warmth cannot be controlled and is disclosed. A provider may not support caching or may require a larger reusable prefix; a failed target remains visible.

The default maximum is a call budget, not permission to spend. Configure the provider boundary's monetary limit and accurate token/rate limits when available. The notebook exposes separate controls for inference, cache experiments and load testing.

## Self-host throughput

`measure_self_host(config, enabled=True, hardware=..., deployment_confirmed=True)` requires a `live_open_weight` route with `deployment: self_hosted`. Identify `description`, `runtime` and `model_revision` in the hardware dictionary. Hosted inference by itself is not a measurement of your own hardware.

Select this deployment through the notebook's separate `SELF_HOST_CONFIG_PATH`. For the gateway cost comparison, the main live profile's open-weight route uses `deployment: hosted`. Keep the application source, effective pipeline settings and test traffic identical between profiles. Record the actual model identity and revision for each deployment.

Each worker runs the same `Application.handle_message` on isolated store/session state. Four important distinctions are retained:

- elapsed time is wall time for the whole concurrent run, not the sum of overlapping request times;
- completed conversations and quality-passing conversations are reported separately;
- model calls and generated tokens have separate rates;
- the result is observed throughput at a specified concurrency, not a saturation claim.

Run a concurrency sweep on the chosen Colab/self-host runtime if needed. Do not use simulator latency or a vendor's quoted tokens per second as your measured capacity. Injected test transports are labelled `test_transport` and cannot produce a live-evidence verdict.

## Break-even

`build_breakeven_input(load_dir, comparison_dir, assumptions, out=...)` connects the saved full live comparison and a one-repeat self-host measurement. It validates source artifact hashes, identical traffic and store fixtures, complete coverage, served model identities and available token-cost evidence. Runs with uncertain retry billing are rejected for this matched cost comparison. Supply only the economic assumptions: monthly hardware cost, variable cost, available hours and planned utilization, with their basis. The function calls the validated `scripts.breakeven.compute_breakeven` calculation and saves both inputs and results. Model quality remains beside the cost result.

The formula is fixed monthly cost plus variable cost per completed request, compared with the matched remote cost per request. These costs remain usage-and-tariff estimates until reconciled with invoices.

Until those measurements and assumptions exist, the notebook prints `NOT_MEASURED`. No hardware, price, model or savings result is invented.
