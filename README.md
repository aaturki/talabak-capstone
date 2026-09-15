# Talabak

An Arabic/English assistant for a fictional retail store: order status, returns, exchanges and store appointments. It saves actions locally after checking session authority and receiving confirmation for the specific proposed action.

**Owner:** تركي أحمد الصليع  
**Programme:** SDAIA Academy — SDA-AIE-213, LLM Application Engineering  
**Cohort dates:** Not supplied; enter the correct dates before submission.  
**Track:** D — Retail order support  
**References:** [Course](https://mohammadyusif.github.io/llm-application-engineering/) · [Capstone requirements](https://mohammadyusif.github.io/llm-application-engineering/capstone.html) · [SDAIA Academy](https://github.com/SDAIAAcademy)

## Submission and execution: one notebook

Open `Talabak_Capstone.ipynb` in Jupyter, or upload **only that notebook** to Google Colab and select **Runtime → Run all**. The notebook embeds the application, data and tests. Its first setup cell extracts a new working directory, installs the versions pinned in `requirements.txt`, starts the local simulator and checks readiness. No provider key or GPU is required. Initial dependency installation needs Internet access. Actual Colab success must be documented by running it there.

The notebook provides the conversation, four demonstrations, tests and generated reports. Saved execution outputs provide the evidence; cells alone do not establish success. The reviewer needs no separate website, Docker setup, CI pipeline or manual local installation.

This version is an **embedded-source snapshot for local review**. The course template clones the project's repository in Colab. Adding the real repository URL and verifying that setup in a fresh Colab runtime remain pending authorized publication. No URL is invented, and extracting an archive does not prove that a clone occurred. Adjacent source files are development materials, not additional submissions.

## Quick conversation examples

The default session represents fictional customer `CUST-A`: a trusted demonstration identity, not production authentication.

| Enter | Expected behaviour |
|---|---|
| Where is my order ORD-1002? | Show the status of an order owned by the session. |
| I want to return ORD-1001 because the product is unsuitable. | Check policy and propose the action for confirmation. |
| Confirm | Execute only the action proposed in the preceding message. |
| Exchange ORD-1001 with SKU-H200. | Check ownership, eligibility, price and stock before confirmation. |
| Book an appointment SLOT-001. | Check capacity, then request confirmation. |
| What are the store hours? | Answer from the fictional store's data. |
| I want to speak to support. | End the automated path locally; send no external message to a person. |

Use a new demonstration session/store for a new action if that order has already been processed. Repeating confirmation must not create a second return or appointment. The notebook also demonstrates Arabic customer messages.

## What local execution establishes

The application makes real OpenAI SDK calls over HTTP to a **loopback simulator**. The gateway implements `tool_calls`, `usage` and `json_schema` response shapes and deliberate faults for repair, retry and fallback tests. Configuration aliases such as `primary`, `open_weight` and `judge` all select simulated routes.

| Evidence | Interpretation |
|---|---|
| SDK, tools, Pydantic, guards, gateway and persistence | Supported by the attached local tests when those tests pass. |
| Simulator cost | External provider spending is zero; `simulated_cost_usd` uses a separate illustrative tariff. |
| Commercial versus open-weight quality | Requires two actual models on the same dataset. The simulator does not establish it. |
| Judge calibration | Requires genuine human labels and calculated agreement/κ. The assistant does not fill human labels. |
| Self-hosting break-even | Requires measured throughput on identified hardware. Simulator latency is not LLM throughput. |
| Peer review and cohort dates | Require external information or evidence not yet supplied. |

Reports separate passed checks, failures and unmeasured items. No grade is guaranteed. GitHub publication and platform submission require the owner's explicit instruction.

## Source layout

```text
Talabak_Capstone.ipynb   Single notebook with source and runnable evidence
config/                Route aliases, bounds and illustrative tariffs
data/                  Fictional store and original evaluation datasets
prompts/               Versioned instructions and judge contracts
talabak/               Model boundary, simulator, policies and pipeline
tests/                 Contract, safety and behaviour tests
scripts/               Evaluation, calibration and notebook generation
docs/                  Decisions, context budget and evidence documentation
```

See [DECISIONS.md](docs/DECISIONS.md) for trade-offs and [CONTEXT_BUDGET.md](docs/CONTEXT_BUDGET.md) for measurement. Store data, prices, policies, customers and orders are **synthetic**. The reference clock is fixed in the data so eligibility and appointment checks remain reproducible.

## Attribution

The course [Murshid reference implementation](https://github.com/MohammadYusif/llm-application-engineering) informed the model boundary, layered pipeline, repair loop, evaluation and cost-evidence practices. Talabak has its own retail domain, tools, policy data, guard cases and evaluation data. Course or student benchmark numbers are not reused as this project's results. The separate course audit records precise sources and the difference between the Capstone and Lab 5 golden-set minimums.
