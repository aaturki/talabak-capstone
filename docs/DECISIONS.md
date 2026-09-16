# Decision log

This log explains local implementation choices. Experimental results come from execution artifacts and reports; design intentions do not substitute for measurements.

## ADR-001 — Track D and the pipeline

Track D combines policy questions with actions that change an order or appointment. The application separates guards, routing, grounded store answers, tools and support handoff. Evaluation, demonstrations and conversation use the same application entry point. Each stage can therefore be tested, and costs attributed to model calls actually made.

The Talabak name, electronics-store domain and SQLite database are project choices, not instructor requirements. The scope covers local requests for return/exchange processing and demonstration bookings. It does not issue refunds or ship products.

## ADR-002 — Model boundary and default simulator

`ModelClient` separates the application from the SDK. The SDK implementation is in `talabak/llm.py`; model names and bounds come from configuration. The local gateway implements the HTTP contract, so schema, tools, usage and errors are tested through that boundary rather than direct calls into simulator logic.

Every default route is simulated, including `open_weight` and `judge`. The owner authorized preparation for real providers while deferring provider and credential selection. Live routes therefore require an explicit opt-in and separate configuration; default runs still ignore credentials and stay on loopback. Live mode validates the configured endpoint, capabilities and spending bounds, then reads only the selected secret. A live comparison still requires actual access and a rerun of the same evaluation. Renaming an alias does not create a live model run.

## ADR-003 — Authority, confirmation and persistent state

Order ownership and action authority come from the session and local records. The model cannot grant itself authority through an argument or sentence. Confirmation binds the action, arguments, customer, session and data digest, and applies only to the next message. Changing the data or action invalidates earlier confirmation.

SQLite stores actions and enforces uniqueness and capacity. Eligibility, stock/appointment checks and execution occur in a transaction to prevent duplicate records or overselling. The trusted demonstration session does not replace production authentication; an actual identity provider is needed before external use.

## ADR-004 — Pydantic and versioned instructions

Closed domains use enums. Unspecified fields stay empty instead of being invented. JSON Schema does not replace semantic validation in Pydantic. A first failure returns specific validation errors for repair (error type, located path and the validator's message; rejected values are never echoed), and processing stops after bounded attempts. Since 2026-09-16 the simulator keeps answering with malformed JSON until the repair instruction is actually on the wire, so the drill proves the message is sent. Tests cover success, successful repair and final failure.

Instructions are versioned files, and the served version is recorded. Repair and judge instructions follow the same rule; an experiment must not silently change an older version. Groundedness and completeness are separate judge dimensions so one call does not return an ambiguous combined score.

## ADR-005 — Safety before model calls and delivery

Normalization, deterministic detection and PII masking precede model calls and text logging. The outbound guard checks leaks, personal data and relayed instructions. Refusals do not repeat attack text. Evidence includes attack and legitimate corpora together, plus assertions that rejected requests do not change order state. A high block rate alone is insufficient without a false-positive rate.

These guards are tested within the stated dataset scope; they do not prove protection against every possible attack wording. Trusted session authority and code-enforced policy remain defenses when model interpretation fails.

## ADR-006 — Evaluation and baseline integrity

Project data was authored around its domain and operations, with source cases and expectations separated from system answers. The Capstone page requires at least 40 golden cases; Lab 5's “Your turn” requires 120. At least 120 meaningful cases, an Arabic majority and explicit strata cover both statements. Expectations must not be changed solely to turn failure into success without a documented domain reason.

Safety checks are deterministic and must pass 100%. The regression gate compares saved results from before a change and reports failures by slice. Model judgment is a separate quality signal. Human calibration remains unestablished until genuine labels, annotator identifiers, matching output versions and calculated κ are available. Automatically generated labels are never described as human labels.

## ADR-007 — Caching, cost and latency

Cache keys include relevant source and policy versions, model, arguments and context. Customer content and order actions must not be reused across customers. A semantic tier requires a measured threshold and near-miss suite; otherwise that requirement remains an explicit gap.

Logs separate actual spending, which is zero in simulator mode, from illustrative cost calculated using usage and an assumed tariff. Before/after comparisons require the same data and an evaluation verdict for each configuration. Local cache and latency measurements do not establish live prices or speed. No GPU hosting recommendation or measured break-even is made before throughput, hardware conditions, concurrency and hourly cost are available.

## ADR-008 — A decision reversed after measurement

After exact matching was implemented, enabling semantic caching was a candidate optimization. Both were measured on 124 repetitive synthetic requests, with a complete golden evaluation per configuration. Exact matching used 84 model calls; adding the semantic tier used 86. Both passed evaluation. Semantic matching required a guard call for new wording, so additional hits did not all produce net savings.

The default was changed to exact matching alone. The semantic tier remains available for experiments and is disabled by default. This trades broader reuse against checking cost, based on `artifacts/cache_benchmark.json`. The measurement uses a simulator and deliberately repetitive traffic; revisit the decision with real models and traffic.

## ADR-009 — One notebook for submission

The submission is one Colab notebook that reaches an internal conversation through **Run all**. Its first setup cell installs dependencies, starts the backend and verifies readiness. The separate website created during development was removed from submission scope. The reviewer needs no Docker setup, CI pipeline or manual local installation.

The earlier encoded source archive made the notebook difficult to inspect and differed from the lab template. It was removed after the owner's review. The replacement setup clones the actual project repository in Colab and verifies the readable source files against a hash manifest. Local review uses the existing checkout. Initial dependency installation needs Internet access. Local notebook success and actual Colab success remain separate evidence categories.

The repository URL and pinned source revision must be supplied before publication and fresh Colab verification. The notebook reports an incomplete locator explicitly; it does not clone the instructor's repository as if it were Talabak or silently invent a public URL.

The README uses the owner's exact supplied name, Turki Ahmed Alsulayyi (تركي أحمد الصليع), and the cohort the owner confirmed on 2026-09-16: second cohort, 13–16 September 2026. Authorization for publication and submission is recorded in the commit history when it is given; nothing is published before that.

## ADR-011 — The shared public prefix is on by default

Before 2026-09-16 the stable prefix (`prompts/context.v1.md` plus public policy, hours, catalogue and tool contracts) existed but was off, so every recorded run showed 0% cached input: the per-stage system prompts are 99–145 tokens, below the simulator's 1,024-token cache minimum. The simulator cache benchmark was extended with a `stable_public_context` step (prefix on, response caching off, so cached tokens come only from the provider usage field). Measured on the frozen 124-request replay with a cold simulator cache (`artifacts/cache_benchmark.json`): baseline 336 calls, 174,664 input tokens, 0% cached, illustrative cost $0.208984; with the prefix 336 calls, 577,960 input tokens of which 96.3% cached, $0.194998 (6.7% lower under the 25% cached-input tariff); with the prefix plus exact response caching 84 calls, 97.2% cached, $0.047789 (77.1% lower). Every step passed the full 144-case golden evaluation and the regression gate.

Decision: `pipeline.stable_context` is `true` in `config/models.json`. The prefix is useful public context, not padding, and it keeps the dynamic content (customer text, tool receipts, repair feedback) at the tail as the course's caching discipline requires. Trade-off: each call carries about 1,200 more input tokens; the net cost depends on the provider's cached-input discount and minimum cacheable length, which the simulator cannot establish. Rule: the live cache measurement (`scripts/live_benchmark.py measure_cache`) reruns the golden set with and without the prefix; if the with-prefix step fails its evaluation verdict on a real model, or the provider reports no cached tokens, revert the default and record the measurement here.

## ADR-012 — Confirmation and grounding no longer depend on byte-exact model output

The audit found three places where a paraphrasing real model would turn a correct outcome into an error: the final Answer had to equal the tool message byte for byte; a confirmation turn asked the model to re-issue the identical tool call (any change in `reason` raised `tool_action_mismatch` and cleared the pending action); and the tool loop continued after a side-effect result, so a model could hide a pending confirmation behind another lookup. The simulator copies tool text verbatim, which is why 144/144 never exposed this.

Decisions: (1) the delivered message is always the tool result; the model's final text is compared and recorded in the trace as `verbatim`, `normalized`, `divergent` or `unparseable`, and only an answer with no tool evidence at all is an error. (2) A confirmation word executes the digest-bound pending action directly (`Application._execute_confirmed`); no model round runs on that turn, which is both safer and cheaper. Confirmation words tolerate punctuation, case and hamza variants. (3) A side-effect or terminal tool result ends the turn. (4) Low router confidence is a clarification, not a terminal handoff; only the handoff tool ends automation. (5) The pending digest binds the action's own order, product, slot and open-action rows plus policy and date, so another customer's committed action no longer invalidates a pending confirmation. These were verified by `tests/test_audit_fixes.py` and the full simulator run; a real model has still not exercised them.

## ADR-013 — Guard evidence is reported per layer and the corpora grew after a recorded miss

The reported 0% false-positive rate covered only the deterministic layer; the classifier stand-in in the simulator refused three legitimate corpus cases (L013, L035, L036) end to end. The guard evaluation now runs both corpora through `Application.handle_message` and reports block and false-positive rates for the deterministic layer alone and for the whole pipeline, naming the layer that blocked each case. The classifier stand-in and `guard.v2.md` gained the same carve-outs (questions about a term, quoted or reported scams, negations).

Twelve attack phrasings and ten legitimate traps were added on 2026-09-16 after a probe of the pre-fix deterministic layer recorded 9 of the 12 attacks missed and 5 of the 10 legitimate requests falsely blocked (`docs/DATASET.md`). They are development cases: the fix was made after seeing them, so they are regression checks, not a blind test. The outbound guard now inspects long payloads instead of refusing them, and detects the canary after normalization (lower case, zero-width, full-width, spaced).

## ADR-014 — Provider portability: strict keyword subset and a tool-only wire pattern

OpenAI's strict mode rejects `minLength`/`maxLength`; every Pydantic-generated wire schema is now filtered to the documented strict subset, while Pydantic keeps enforcing those limits on parse. Providers that cannot combine a response schema with tools (Groq documents this; vLLM has an open request) are served with tool-only turns when `schema_with_tools` is false, and the wire pattern is recorded per usage row and in run provenance. The kept-verbatim alternative, failing fast, would have excluded the course's own vLLM self-host route from the tools stage.

## ADR-015 — Live providers chosen, a guard prompt reversed by the first live run, and the routing recommendation

On 2026-09-16 the owner supplied keys and the live comparison ran over the same 144 golden cases with response caching and fallbacks disabled (`artifacts/live/20260916T160121Z-409d8f927a/`). Commercial route: OpenAI `gpt-5-mini` (served `gpt-5-mini-2025-08-07`, reasoning effort minimal, strict `json_schema` plus strict tools in one request). Open-weight route: DeepSeek `deepseek-flash`, whose DeepSeek-V4-Flash weights are public on Hugging Face, served in JSON mode plus tool-only turns because its API offers `json_object` rather than a strict schema. Groq's free tier (token-per-minute limits), Cerebras (payment required) and Mistral's unactivated free plan were tried and rejected on the day; the configuration records only what actually ran.

The first full commercial run used `guard.v2` and blocked eight ordinary golden requests (unknown or malformed identifiers, a masked phone number, "without a signed-in customer"); six were safety cases. That reversed the prompt: `guard.v3` states that identifiers, own contact details and requests the application may later deny are legitimate and that uncertainty must not block. Re-run on the same cases, six of the eight passed; two borderline phrasings (G042, G104) still tripped the classifier. The official run then scored **140/144** (safety 75/78) on gpt-5-mini and **137/144** (safety 73/78, one operational error on G076) on deepseek-flash, against 144/144 on the simulator. Every miss is a classifier false positive or a paraphrase divergence, never an unauthorized write: action counts and denials stayed correct on both routes. The live safety stratum is therefore not 100%, and the report says so.

Cost and cache, from provider usage fields and dated tariffs: gpt-5-mini 388 calls, 625k input tokens of which 72.8% cached, about $0.084; deepseek-flash 413 calls, 807k input tokens of which 72.3% cached, about $0.135 at peak rates; median case latency 4.6 s versus 3.6 s. The ≥65% cached-input target holds on both real providers with the shared public prefix on by default (ADR-011).

Routing recommendation for this workload: keep `gpt-5-mini` as the primary route (higher golden and safety pass rates, strict schema enforcement, lower estimated cost on this traffic) and keep `deepseek-flash` configured as the open-weight alternative for cost-insensitive or latency-sensitive traffic once its two extra classifier false positives are addressed. No self-host break-even is computed: no throughput was measured on owned hardware, and asserting one without a measurement would violate ADR-007.

## Current recommendation

Use the live comparison in `EVALUATION_REPORT.md` ("Live model runs") as the routing evidence: gpt-5-mini primary, deepseek-flash as the open-weight alternative. Judge calibration (human labels, κ) and the self-host break-even remain the two unfinished measurements; both are reported as missing rather than estimated.

## ADR-010 — Real evidence without replacing the default course setup

The same SDK boundary can address a commercial service and an open-weight endpoint through configuration. Required structured-output and tool capabilities are checked rather than silently removed for a weaker provider. A configured secret is loaded only for explicitly enabled live runs. Provider responses identify the served model and returned usage; unknown usage remains unknown. Estimated token cost is distinct from an invoice. Injected test transports never count as live model evidence.

Live comparison, human review, cache experiments and self-host load tests have separate notebook controls. This keeps default Run all usable without paid inference while providing executable paths for the additional evidence. Human labels are exported blank and tied to actual answer hashes. Current tests of these paths establish engineering readiness, not model quality, calibration or a grade.

The optional context-prefix experiment supplies public policies, catalogue facts and tool contracts. Private order/session data is excluded. It is tested before enabling it in the main pipeline because extra context can increase cost or change quality. The cache benchmark records every phase's full golden result, including a failed optimization. It cannot force a provider's cache to meet the course target.

## References

- [Capstone requirements](https://mohammadyusif.github.io/llm-application-engineering/capstone.html)
- [Setup and classroom-gateway distinction](https://mohammadyusif.github.io/llm-application-engineering/setup.html)
- [Simulator evidence limits](https://mohammadyusif.github.io/llm-application-engineering/reference/gateway.html)
- [Module 5: evaluation](https://mohammadyusif.github.io/llm-application-engineering/modules/m5-evaluation.html)
- [Module 6: cost and caching](https://mohammadyusif.github.io/llm-application-engineering/modules/m6-cost-latency-caching.html)
