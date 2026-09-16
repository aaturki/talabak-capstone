# Real-provider configuration

Provider integration is disabled by default: `SDKClient()` and `config/models.json` use the local simulator with no API key. The live comparison recorded on 2026-09-16 used a separate, git-ignored profile (`runtime/models.live.json`) selecting OpenAI `gpt-5-mini` (commercial, `gpt-5` as judge) and DeepSeek `deepseek-flash` (open-weight; JSON mode plus tool-only turns); its sanitized configuration and dated tariffs are recorded in the run manifest. Groq's free tier, Cerebras and Mistral's free plan were tried the same day and could not serve the full run (rate limits or payment required), which ADR-015 records.

## Choose a profile later

`talabak/llm.py` is the application's single SDK boundary. It supports independently configured OpenAI-compatible commercial and open-weight endpoints. Protocol compatibility does not establish tool support or answer quality.

`config/models.live.example.json` is an incomplete template. Its null endpoints, model IDs, capabilities and tariffs must be filled from the selected providers' documentation. Alias names such as `primary`, `open_weight` and `judge` are routing labels, not claims that models are running.

1. Choose the commercial model, open-weight model and judge, verifying their endpoint and capabilities.
2. Copy the template to `runtime/models.live.json` and fill the selected settings. Keep credential values outside JSON.
3. Choose a named environment variable or Colab Secret for each route.
4. Set explicit call and optional estimated-cost limits. Add dated, source-linked tariffs when measuring cost.
5. Run configuration preflight, then explicitly enable the notebook's live section.

```python
from talabak.llm import preflight_config

# A completed configuration, selected later; this does not read secrets or call HTTP.
readiness = preflight_config(live_config, allow_live=True)
```

All routes are validated before the first secret is read. A configured URL or an existing environment key does not enable live access. Close a client with `close()` or a `with` block.

## Named credentials

| Auth configuration | Behaviour after explicit enable |
|---|---|
| `{"type":"env","name":"TALABAK_COMMERCIAL_API_KEY"}` | Read only that named variable. |
| `{"type":"secret","name":"TALABAK_COMMERCIAL_API_KEY"}` | Call the supplied `secret_loader(name)`. |
| `{"type":"none"}` | Allow loopback servers only; the SDK receives a fixed placeholder, not a credential. |

```python
RUN_LIVE = False
if RUN_LIVE:
    from google.colab import userdata
    from talabak.llm import SDKClient
    with SDKClient(config=live_config, allow_live=True,
                   secret_loader=userdata.get) as client:
        # Use the same Application and evaluation runner as the notebook.
        pass
```

Default setup does not call `userdata` or reuse `OPENAI_API_KEY`. Secret-store error details and credential values are excluded from exposed exceptions. The HTTP client disables environment proxies and redirects, and isolates ambient SDK headers and organization settings from the selected routes.

## Capabilities and endpoint contract

| Capability | Meaning |
|---|---|
| `json_schema` | Whether strict structured responses are supported. Required unless `json_object` is true. |
| `json_object` | Optional. If true and `json_schema` is false, structured stages use JSON mode: the schema is sent as a trusted instruction, the provider only guarantees valid JSON, and Pydantic validation plus the repair loop enforce the contract (wire pattern `…+json_object_mode`). |
| `tools` | Whether model tool calls are supported. Required. |
| `schema_with_tools` | Whether one request may combine tools and a response schema. If false, the tools stage sends tool-only turns (`wire_pattern: tools_only` in every tools-stage usage row and in preflight); the delivered message is the tool result in both patterns. |
| `parallel_tool_calls` | Whether to send the corresponding request option. |
| `temperature` | Whether to send temperature. |
| `developer_role` | If false, leading trusted instructions are merged into one system message and later ones (repair feedback) become user turns prefixed `[Application instruction]`, because many open-weight chat templates reject a non-leading system message. |
| `token_parameter` | Explicit `max_tokens` or `max_completion_tokens`. |
| `deployment` (route field) | `hosted` or `self_hosted`; required on the open-weight route before a comparison, because the break-even input accepts only a hosted comparison and the value is hashed into run provenance. |

A route that lacks `json_schema` or `tools` fails before HTTP. Within a fallback chain, kwargs are built per hop: a fallback that cannot serve the request shape is skipped with a recorded `capability_unsupported_hop_skipped` event, and never blocks a capable primary. Live fallback chains cannot cross into simulator routes; controlled comparison disables fallbacks entirely.

Wire schemas are restricted to the strict keyword subset (`strict_wire_schema` in `talabak/schemas.py`: no `minLength`/`maxLength`, every object closed with all properties required). Pydantic still enforces the removed length limits when the response is parsed, so nothing is relaxed. A structured-output refusal (`message.refusal`) is one failed call with `finish_reason: refusal`; it is not retried as malformed JSON. Confirm the strict subset with a single one-token request before a paid run, since OpenAI-compatible servers differ.

Remote endpoints require HTTPS. Loopback `127.0.0.1`, `localhost` and `::1` may use HTTP. Requests are restricted to the configured origin and chat-completions path; credential-bearing URLs, queries, fragments and redirects are rejected. A request stopped by that guard never leaves the process: it is not retried, not counted as a wire call and not reserved against the budget.

## Candidate providers (not selected)

The 2026-09-16 audit checked provider documentation for the capabilities this application needs. These are candidates for the owner's decision, not selections; verify each with one request before spending.

| Route | Candidate | Wire pattern | Notes from the audit |
|---|---|---|---|
| commercial `primary` and `judge` | OpenAI Chat Completions (`https://api.openai.com/v1`), a current small model for primary and a different, stronger model for the judge | `schema_with_tools` | Documents strict `json_schema`, strict tools, `developer` role and prompt caching reported as `usage.prompt_tokens_details.cached_tokens`; the schema-plus-tools combination is community-confirmed, so confirm it once. Use `max_completion_tokens` for reasoning-class models. |
| hosted `open_weight` | Groq (`gpt-oss-120b`, Qwen3-class) or Fireworks/Together (Llama 3.3 70B, Qwen3) | `tools_only` | Groq documents that structured outputs cannot be combined with tools; the others do not document the combination. Groq reports cached tokens with a minimum prefix length and a cached-input discount. |
| self-hosted `open_weight` | vLLM with `--enable-prefix-caching --enable-prompt-tokens-details --enable-auto-tool-choice --tool-call-parser hermes`, e.g. Qwen2.5-7B-Instruct-AWQ on a Colab T4 or the owner's local GPU behind loopback `auth: none` | `tools_only` | vLLM's combined structured-output-plus-tools request is still an open feature request. A rented GPU must be reached through an SSH port-forward to loopback because remote live routes require HTTPS. |

Order-of-magnitude cost assumptions from the same audit, before any run: the full two-route comparison is roughly 1,000–2,000 calls and 0.7–1.4M input tokens (a few dollars with small models); the cache benchmark roughly 2,850 calls (under about $2 with small models); the judge under $0.20; self-host throughput $0 on a Colab T4 to a few dollars on a rented GPU. These are assumptions, not quotes or invoices.

## Measurement fields

Missing measurements remain `null` rather than becoming zero:

- `input_tokens`, `output_tokens`, `cached_tokens` come from provider usage, with availability/status fields.
- `requested_model` records configuration; `served_model` records the response. Missing identity is marked by `served_model_known:false`.
- `cost_usd:null` means no verified invoice is available from a chat response.
- `estimated_cost_usd` uses supplied tariffs and complete usage; it is null when the evidence is insufficient.
- `estimated_cost_upper_bound_usd` ignores cache discounts when a conservative bound is possible.
- `simulated_cost_usd` remains separate from live estimates.

When cached-token usage is missing and cached/uncached prices differ, exact estimated cost remains unknown. Invalid usage, such as cached tokens exceeding input tokens, is rejected.

Every HTTP attempt has a unique counter and safe usage metadata, including malformed responses. HTTP failures have unknown chargeable usage. Events omit prompt text, headers, raw provider errors and credential values. Injected test transports always report `test_transport`, even when their configuration names a live route. Declaring a route open-weight still requires documenting the actual served model and deployment.

## Budgets and concurrency

Optional settings:

```json
{"budget": {"max_calls": null, "max_estimated_cost_usd": null}}
```

`max_calls` counts HTTP attempts, including retries and fallbacks, over one client's lifetime. Reservations and reconciliation share a lock; network calls occur outside the lock so concurrent work can proceed. `client.budget_status` reports `wire_calls`, `estimated_cost_usd` (complete-usage responses only), `estimated_cost_upper_bound_usd` (every metered response, cache discounts ignored), `reserved_estimated_cost_usd` (the amount compared with the cap), `partial_usage_responses`, `unknown_usage_responses`, `retained_failure_reservations` and `stopped`.

A cost limit requires all tariffs and an input bound per route. The client reserves an input/output allowance before sending and reconciles known usage afterward. An HTTP rejection (429, 4xx, 5xx) carries no billable usage, so its reservation is released and the retry or fallback hop can proceed under the cap. A timeout or connection failure may have been processed by the provider, so its reservation is retained and counted in `retained_failure_reservations`. Missing usage under a cost limit blocks subsequent requests. Parallel requests cannot reserve the same allowance.

This is an estimated limit, not an invoice guarantee. The input screen counts tokens with the bundled `o200k_base` vocabulary plus a small per-message margin (a byte-based fallback applies if the tokenizer cannot load); the reservation itself is `max_input_tokens` times the input rate, so set `max_input_tokens` to the real context you allow rather than a padded value. Provider fees and billing rules may differ. Separate clients or processes require additional provider-side spending controls. GPU and hosting costs are not inferred by this client.

## Validation scope

The integration was checked against installed `openai==2.54.0` SDK interfaces and local HTTP fixtures. `tests/test_llm_live.py` covers opt-in, named secrets, capabilities, endpoints, malformed or missing usage, header isolation, fallbacks, and concurrent call/cost limits. No real credentials or external model calls are used by these tests.

Passing these tests establishes integration behaviour. Real-model quality, prompt-cache savings, human agreement and serving throughput still require the explicitly enabled experiments documented in [Live evaluation](LIVE_EVALUATION.md) and [Measurements](LIVE_MEASUREMENTS.md).
