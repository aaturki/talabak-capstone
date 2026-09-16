# Model gateway: local execution and evidence limits

## Established behaviour

The project uses the **OpenAI Python SDK** to make actual HTTP requests to a local service. That service is a **deterministic Track D simulator**. No model weights run behind it, no paid provider is contacted, and no personal key is required. The SDK identifies the connection contract; it does not imply that an OpenAI model was run.

The [setup page](https://mohammadyusif.github.io/llm-application-engineering/setup.html) and [gateway reference](https://mohammadyusif.github.io/llm-application-engineering/reference/gateway.html) were retrieved with HTTP 200 on 15 September 2026. They describe a default simulator that needs no key or GPU. Mention of a separate classroom gateway establishes neither its address nor its availability; it was not contacted.

## Course simulator and local extension

The source inspected and tested was [course commit de2ff3c](https://github.com/MohammadYusif/llm-application-engineering/tree/de2ff3c0d8758c77d85c944e2d6f133647b84a91), particularly `murshid/infra/mockgw/app/{main,brain}.py` and `src/murshid/llm/{openai_compat,resilient}.py`.

The **unmodified course code** was started on a temporary loopback port and received three SDK requests:

1. Its original `check_application_status` tool contract succeeded.
2. It did not issue the retail `lookup_order` tool call.
3. It did not return this project's `DomainRequest` schema.

Full responses and source-file hashes are in [STOCK_GATEWAY_PROBE.json](STOCK_GATEWAY_PROBE.json). The government-services simulator was therefore not treated as a ready-made retail backend.

`talabak/mock_gateway.py` is a project-specific extension inspired by the course gateway contract: deterministic Arabic/English extraction, correlated tool calls, JSON replies from tool results, fixed-prefix caching and injectable HTTP failures. It imports neither evaluation data nor the store database. Final-answer facts come from `message` and `sources` in a tool result with a matching call identifier. Student projects' quality rules or results are not copied.

`GuardDecision` is a stand-in for a classifier: it blocks on a short list of trigger phrases unless the text reads as a question about a term, an explanation request or a scam report (`CLASSIFIER_META_CONTEXT`). This is a documented heuristic; the guard prompt's wording is not interpreted.

`JudgeVerdict` tests the judgment contract only. An answer appearing verbatim in the evidence receives PASS; numbers absent from the evidence receive FAIL; lexical overlap alone receives PARTIAL. Each reason starts with `simulator_contract`. These explicit superficial rules do not establish judge quality or human calibration. Inputs contain only the question, trusted evidence and candidate answer.

`prompts/router.degraded.v0.md` is a deliberate regression fixture. Its exact system-message header makes the simulator route requests to FAQ. The comparison run uses it to test the regression gate against the same data. It is neither the default route nor a measurement of a live model's response to prompt changes.

The extension supports **OpenAI-compatible chat/completions only**. It does not implement Anthropic, streaming or TTFT measurement; those are features of the original course simulator. All aliases—`primary`, `fallback`, `judge`, `open_weight`—select local rules. The `open_weight` name does not establish that an open-weight model or a model comparison was run.

## Execution

The notebook's first setup cell starts and checks the gateway automatically. These commands are optional development entry points from the project root after installing dependencies:

```console
python -m uvicorn talabak.mock_gateway:app --host 127.0.0.1 --port 8080
python -m pytest tests/test_llm.py -q
```

For code that needs an automatically selected free port:

```python
import json
from talabak.llm import SDKClient, DEFAULT_CONFIG
from talabak.mock_gateway import running_gateway

with running_gateway(port=0) as base_url:
    config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    for route in config["routes"].values():
        route["base_url"] = base_url
    with SDKClient(config=config) as model:
        # Pass the ModelClient to the application here.
        pass
```

The context shuts the service down without opening a window or external process. Defaults live in `config/models.json`. The client ignores `OPENAI_API_KEY`, `OPENAI_BASE_URL` and environment proxy settings. It rejects external network URLs and URL credentials for simulator routes. Live routes exist behind an explicit opt-in (`allow_live=True`, named secrets, HTTPS or loopback) described in [PROVIDERS.md](PROVIDERS.md); the default configuration and this document concern the simulator.

## Structured output, tools and reliability

- The application depends on the `ModelClient` Protocol, not SDK objects.
- The client sends `response_format.type=json_schema`, `strict=true` and the complete schema.
- Tool definitions use strict JSON Schema. The client decodes tool arguments to an object and retains the call `id`.
- Truncated output (`finish_reason=length`) is rejected, with its usage preserved in the runtime error.
- Internal SDK retries are disabled. The policy allows two attempts per route, exponential backoff with jitter, `Retry-After` capped at two seconds, then an explicit fallback route.
- Connection errors and HTTP 408/409/425/429/500/502/503/504/529 are retried. HTTP 400/401/403/404 are neither retried nor redirected to fallback.
- Malformed content JSON reaches the application for bounded schema repair. The client does not invent a valid object in place of a malformed reply.

## Tokens, caching and cost

The simulator uses `o200k_base` to count its specified text representation of messages, tools and schemas. These are actual counts of that simulator representation, **not a verified provider bill or live-model chat-template count**. The cache prefix includes the system message, tools and schema; user messages and changing context remain outside it. The minimum is 1,024 tokens. TTL is 300 seconds, refreshed on a hit. Keys vary with the model and prefix digest.

`usage` contains `input_tokens`, `output_tokens`, `cached_tokens`, `attempts`, `fallback_used`, `alias`, `finish_reason` and `latency_ms`. Latency measures the actual local request, including delays and retries. It does not establish live inference latency or LLM throughput.

`cost_usd=0` represents actual external API spending in this mode. `simulated_cost_usd` separately applies explicitly configured illustrative tariffs, distinguishing cached and uncached input. These tariffs are **educational assumptions**, not provider prices. Failed calls are not assigned invented usage; injected HTTP faults occur before response generation and token usage.

The tokenizer vocabulary is bundled in `config/tokenizer_cache` to avoid a first-run download. Its source is the [official OpenAI file](https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken), used through [tiktoken](https://github.com/openai/tiktoken). Its SHA-256 matches the hash required by tiktoken:

```text
446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d
```

## Health checks and fault injection

| Endpoint | Function |
|---|---|
| `GET /healthz` | Declare `implementation=talabak-track-d-extension` and `evidence_mode=simulator`. |
| `GET /v1/models` | List local model names. |
| `POST /v1/chat/completions` | Serve the SDK/JSON Schema/tool-call contract. |
| `GET /admin/stats` | Report requests, tokens, cache hits and faults. |
| `POST /admin/reset` | Reset simulator counters, cache and faults. |
| `POST /admin/fault` | Inject a fault scoped by model and duration/request count. |

Example: `{"mode":"overload","model":"talabak-course-primary","seconds":60}`.
Modes are `rate_limit` (429), `overload` (529), `server_error` (503), `timeout` (504), `invalid_json`, `invalid_json_until_repair` (malformed JSON until the request carries the application's `# repair-` developer message), `invalid_tool`, `tool_loop` and `off`.

Here `timeout` means an **immediate injected HTTP 504**, not a measured network timeout. Connection failure is tested separately with a controlled httpx transport.

## Test evidence and limits

The initial run of `tests/test_llm.py` on 15 September 2026 passed 38 cases in 4.59 seconds. That historical snapshot covered real local HTTP, Arabic/English extraction, tool-result correlation, cache measurement and invalidation by TTL/prefix/model, retries, fallback, truncated outputs and malformed arguments. Current counts and times come from `artifacts/pytest.txt` and the executed notebook (375 tests on 16 September 2026); this snapshot is not a fixed performance promise.

These tests establish neither actual model understanding nor independent human judgment, commercial/open-weight comparison or GPU/LLM throughput. Those require separate evidence.

`test_llm.py` and `test_safety.py` cover forged authority, confirmation, replay, contention for the last product or appointment, output/audit leakage, and preserving every generation's usage through JSON decoding failures or truncation. Across the development set with an injected 429, summed `usage.attempts` matches recorded HTTP attempt events. The notebook provides current test counts and timings. Separate website tests were archived when submission scope became notebook-only.

Review found and fixed four request-lifecycle gaps with regression tests: confirmation surviving a rejected tool result, model-generated PII reaching the audit log, unchecked FAQ citations, and private exception text entering logs.
