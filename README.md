# Talabak (طلبك) — a bilingual retail order-support assistant

**Capstone · Track D · retail order status, returns, exchanges and store appointments**

**Turki Ahmed Alsulayyi (تركي أحمد الصليع)** — Large Language Model Application Engineering (Second cohort), run 13–16 September 2026, SDAIA Academy (course code SDA-AIE-213).

Talabak is the customer-support assistant of a fictional Saudi electronics store. Customers write in Arabic or English; it answers policy and catalogue questions from the store's own data, looks up only the orders the authenticated session owns, proposes returns, exchanges and store appointments through tools, and writes an action only after the customer confirms that exact action in the next message. Everything else it refuses or hands to a person.

Every claim about it is checkable by running it: the notebook carries its own execution history, the evaluation report, the meter output and the corpus numbers.

## Open it

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/aaturki/talabak-capstone/blob/main/Talabak_Capstone.ipynb)

**Runtime → Run all.** No local install and no API key. The first cell clones this repository at the pinned source commit, verifies the source hashes, installs the pinned dependencies and starts a loopback simulator that stands in for a model provider, so every number the notebook prints is a measurement of this application rather than a claim about a vendor. The notebook then runs the tests, the 144-case evaluation, the cache benchmark, four demonstrations and an interactive Arabic/English conversation. Real-provider evidence (OpenAI and DeepSeek over the same golden set) is recorded separately in [EVALUATION_REPORT.md](EVALUATION_REPORT.md) under "Live model runs".

The setup follows the course labs: readable source files imported after a clone, no encoded archive inside the notebook. See [Notebook setup](docs/NOTEBOOK_SETUP.md).

### Run it locally

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt
```

```bash
.venv/Scripts/python scripts/run_all.py
```

Python 3.11 or newer (3.12 was used). On macOS or Linux the interpreter is `.venv/bin/python`. The third command reproduces the tests, evaluations, cache benchmark and both reports without any notebook front end. To use the notebook itself, open `Talabak_Capstone.ipynb` in any Jupyter front end you already have (JupyterLab, VS Code or Colab) with this virtual environment as the kernel; its first cell starts the loopback simulator itself, so no key, GPU or extra service is needed.

## Default mode and real providers

The default backend is a deterministic simulator reached through the provider SDK. It exercises schemas, tool calls, authorization, repair, retries, accounting and regression checks. Its responses and timing do not establish real-model quality or hardware performance.

Real-provider support runs through the same boundary from a separate configuration. The recorded live comparison uses OpenAI `gpt-5-mini` (commercial; `gpt-5` as judge) and DeepSeek `deepseek-flash` (open-weight; the DeepSeek-V4-Flash weights are public on Hugging Face), with keys read only from named environment variables or Colab Secrets. No external model call is made by default, and no existing credential is silently reused.

- [Provider configuration](docs/PROVIDERS.md)
- [Live evaluation and human review](docs/LIVE_EVALUATION.md)
- [Cost, caching and self-host measurements](docs/LIVE_MEASUREMENTS.md)

The optional experiments evaluate the same application used by the conversation. Simulator, injected-test and live-provider evidence remain distinguishable. Missing usage, human labels, cache measurements or throughput are reported as unavailable rather than filled with estimated results. Token-cost estimates are labelled separately from actual invoices.

## Try a conversation

The default session represents fictional customer CUST-A. It is a demonstration identity, not production authentication.

| Message | Behaviour |
|---|---|
| Where is my order ORD-1002? | Return the status only if the session owns it. |
| I want to return ORD-1001 because the product is unsuitable. | Check policy and propose a specific action. |
| Confirm | Execute only the action currently awaiting confirmation. |
| Exchange ORD-1001 with SKU-H200 because I need another model. | Check ownership, eligibility, stock and confirmation. |
| Book an appointment SLOT-001 for a product demonstration. | Check availability and request confirmation. |
| What are the store hours? | Answer from the store's public source data. |
| I want to speak with a human agent about my order. | End the automated path locally. |

Arabic examples are demonstrated in the notebook. Reset the demo store/session to try an independent action after an order has already been processed. Repeating confirmation must not create another action.

## Evidence and remaining execution

| Area | Current evidence boundary |
|---|---|
| Application engineering | Local tests and executed notebook outputs; see the current execution record. |
| Real model comparison | Recorded on 2026-09-16: OpenAI gpt-5-mini 140/144 and DeepSeek deepseek-flash 137/144 over the same golden set, by slice, with cost, cache and latency (EVALUATION_REPORT.md, "Live model runs"). |
| Human calibration | Measured on 2026-09-16: 40 owner-labelled live answers against the gpt-5 judge; agreement 42.5%, κ = −0.02 (v2 rubric), status NOT_CALIBRATED; the judge stays advisory (ADR-016). |
| Provider caching and savings | Measure returned usage and rerun evaluation after each optimization. |
| Self-host break-even | Requires the selected runtime's measured throughput and explicit economic inputs. |
| Reproducibility | Local execution and actual Colab execution are recorded separately. |

See [RUBRIC_EVIDENCE.md](RUBRIC_EVIDENCE.md), [EVALUATION_REPORT.md](EVALUATION_REPORT.md) and [BENCHMARKS.md](BENCHMARKS.md). A prepared experiment is not a completed measurement or a guaranteed grade.

## Development files

The talabak directory contains the application; config contains model and notebook settings; data contains the fictional store and original evaluation cases; prompts contains versioned instructions; scripts contains evaluation and notebook tooling. These files support the one notebook.

## Attribution and design

The instructor explicitly permits borrowing patterns and infrastructure from [Murshid](https://github.com/MohammadYusif/llm-application-engineering/blob/de2ff3c0d8758c77d85c944e2d6f133647b84a91/capstone.qmd#L44-L50). Talabak uses that architectural approach with its own retail domain, tools, policy data, guards and evaluation cases. Course or student benchmark numbers are not reused as Talabak's results.

[Decisions](docs/DECISIONS.md) · [Dataset](docs/DATASET.md) · [Course](https://mohammadyusif.github.io/llm-application-engineering/) · [SDAIA Academy on GitHub](https://github.com/SDAIAAcademy)
