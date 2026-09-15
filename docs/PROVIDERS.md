# Real-provider configuration

Provider integration is prepared and disabled. Providers, models, prices and credentials have not been selected. `SDKClient()` and `config/models.json` still use the local simulator with no API key.

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
| `json_schema` | Whether strict structured responses are supported. |
| `tools` | Whether model tool calls are supported. |
| `schema_with_tools` | Whether a request may combine tools and a response schema. |
| `parallel_tool_calls` | Whether to send the corresponding request option. |
| `temperature` | Whether to send temperature. |
| `developer_role` | If false, convert trusted developer instructions to system messages. |
| `token_parameter` | Explicit `max_tokens` or `max_completion_tokens`. |

Unsupported required schema/tool combinations fail before HTTP. The application requires both structured output and tools. Live fallback chains cannot cross into simulator routes; controlled comparison disables fallbacks entirely.

Remote endpoints require HTTPS. Loopback `127.0.0.1`, `localhost` and `::1` may use HTTP. Requests are restricted to the configured origin and chat-completions path; credential-bearing URLs, queries, fragments and redirects are rejected.

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

`max_calls` counts HTTP attempts, including retries and fallbacks, over one client's lifetime. Reservations and reconciliation share a lock; network calls occur outside the lock so concurrent work can proceed. Inspect `client.budget_status` for remaining limits.

A cost limit requires all tariffs and an input bound per route. The client reserves an input/output allowance before sending and reconciles known usage afterward. Failed requests retain their reservations because their billing is unknown. Missing usage under a cost limit blocks subsequent requests. Parallel requests cannot reserve the same allowance.

This is an estimated limit, not an invoice guarantee. Input sizing uses conservative serialized bytes and margin rather than a provider-specific tokenizer. Provider fees and billing rules may differ. Separate clients or processes require additional provider-side spending controls. GPU and hosting costs are not inferred by this client.

## Validation scope

The integration was checked against installed `openai==2.54.0` SDK interfaces and local HTTP fixtures. `tests/test_llm_live.py` covers opt-in, named secrets, capabilities, endpoints, malformed or missing usage, header isolation, fallbacks, and concurrent call/cost limits. No real credentials or external model calls are used by these tests.

Passing these tests establishes integration behaviour. Real-model quality, prompt-cache savings, human agreement and serving throughput still require the explicitly enabled experiments documented in [Live evaluation](LIVE_EVALUATION.md) and [Measurements](LIVE_MEASUREMENTS.md).
