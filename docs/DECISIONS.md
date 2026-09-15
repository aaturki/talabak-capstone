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

Closed domains use enums. Unspecified fields stay empty instead of being invented. JSON Schema does not replace semantic validation in Pydantic. A first failure returns specific validation errors for repair, and processing stops after bounded attempts. Tests cover success, successful repair and final failure.

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

The README uses the owner's exact supplied name, تركي أحمد الصليع. Cohort dates await the correct information. Current authorization covers local preparation and history; it does not include publication, push, submission or contacting the instructor or peers.

## Current recommendation

Review local simulator results and gaps requirement by requirement. A live commercial/open-weight choice has not been established through measurements; an alias is not a deployment recommendation. When authorized access is available, rerun the same evaluation, cost and latency measurements, then derive the recommendation and break-even from that evidence.

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
