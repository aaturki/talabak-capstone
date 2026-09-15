# Decision log

This log explains local implementation choices. Experimental results come from execution artifacts and reports; design intentions do not substitute for measurements.

## ADR-001 — Track D and the pipeline

Track D combines policy questions with actions that change an order or appointment. The application separates guards, routing, grounded store answers, tools and support handoff. Evaluation, demonstrations and conversation use the same application entry point. Each stage can therefore be tested, and costs attributed to model calls actually made.

The Talabak name, electronics-store domain and SQLite database are project choices, not instructor requirements. The scope covers local requests for return/exchange processing and demonstration bookings. It does not issue refunds or ship products.

## ADR-002 — Model boundary and default simulator

`ModelClient` separates the application from the SDK. The SDK implementation is in `talabak/llm.py`; model names and bounds come from configuration. The local gateway implements the HTTP contract, so schema, tools, usage and errors are tested through that boundary rather than direct calls into simulator logic.

Every default route is simulated, including `open_weight` and `judge`. Access to a live classroom gateway has not been confirmed, and external spending has not been authorized. This build rejects external URLs and ignores environment credentials. A live comparison requires authorized access, documented configuration, review of the connection policy and the same evaluation rerun. Renaming an alias does not create a live model run.

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

The notebook embeds source, data and tests in a compressed payload with a SHA-256 digest. It selects an available loopback port and extracts a new working directory, allowing local review without a public repository. Initial dependency installation needs Internet access. Local `nbclient` success and actual Colab success are separate evidence categories.

Embedding source is a choice for this review snapshot. The course template clones the project's repository in Colab. A real URL can be added after authorized publication and tested in a fresh runtime. Neither that clone nor an actual Colab run has been performed.

The README uses the owner's exact supplied name, تركي أحمد الصليع. Cohort dates await the correct information. Current authorization covers local preparation and history; it does not include publication, push, submission or contacting the instructor or peers.

## Current recommendation

Review local simulator results and gaps requirement by requirement. A live commercial/open-weight choice has not been established through measurements; an alias is not a deployment recommendation. When authorized access is available, rerun the same evaluation, cost and latency measurements, then derive the recommendation and break-even from that evidence.

## References

- [Capstone requirements](https://mohammadyusif.github.io/llm-application-engineering/capstone.html)
- [Setup and classroom-gateway distinction](https://mohammadyusif.github.io/llm-application-engineering/setup.html)
- [Simulator evidence limits](https://mohammadyusif.github.io/llm-application-engineering/reference/gateway.html)
- [Module 5: evaluation](https://mohammadyusif.github.io/llm-application-engineering/modules/m5-evaluation.html)
- [Module 6: cost and caching](https://mohammadyusif.github.io/llm-application-engineering/modules/m6-cost-latency-caching.html)
