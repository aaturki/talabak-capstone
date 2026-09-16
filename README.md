# Talabak — Retail Order Support

An Arabic/English assistant for a fictional retail store: order status, returns, exchanges and store appointments. It checks ownership, policy and confirmation before saving an action.

**Owner:** Turki Ahmed Alsulayyi (تركي أحمد الصليع)  
**Programme:** SDAIA Academy — SDA-AIE-213, Large Language Model Application Engineering  
**Track:** D — Retail order support  
**Cohort:** Second cohort, 13–16 September 2026

## One notebook

The submission is **Talabak_Capstone.ipynb**. Once the actual repository URL and source revision are configured, open its Colab link and select **Runtime → Run all**. The setup cell clones the repository, installs pinned dependencies and starts the default local backend. It needs internet but no API key or GPU. The notebook contains the bilingual conversation, four demonstrations, tests, evaluation, decisions and reports.

The setup follows the course labs. Application source remains readable in the repository; no encoded project archive is embedded in the notebook. A local review uses this existing checkout. The repository URL and actual fresh-Colab execution remain pending; the notebook does not claim that either has already happened. See [Notebook setup](docs/NOTEBOOK_SETUP.md).

### Run it locally

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt
```

```bash
.venv/Scripts/python -m jupyter lab Talabak_Capstone.ipynb
```

Python 3.11 or newer (3.12 was used). On macOS or Linux the interpreter is `.venv/bin/python`. The notebook's first cell starts the loopback simulator itself; no key, GPU or extra service is needed. `python scripts/run_all.py` reproduces the tests, evaluations, cache benchmark and both reports from the command line.

## Default mode and real providers

The default backend is a deterministic simulator reached through the provider SDK. It exercises schemas, tool calls, authorization, repair, retries, accounting and regression checks. Its responses and timing do not establish real-model quality or hardware performance.

Real-provider support is prepared separately. Select a commercial model and an open-weight model through configuration, supply credentials through Colab Secrets, and enable the notebook's live section. Provider choice, prices and credentials are intentionally undecided. No external model call is made by default, and no existing credential is silently reused.

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
| I want to speak to support. | End the automated path locally. |

Arabic examples are demonstrated in the notebook. Reset the demo store/session to try an independent action after an order has already been processed. Repeating confirmation must not create another action.

## Evidence and remaining execution

| Area | Current evidence boundary |
|---|---|
| Application engineering | Local tests and executed notebook outputs; see the current execution record. |
| Real model comparison | Prepared; run after choosing the two providers and budgets. |
| Human calibration | Export actual answers, obtain real human labels, then calculate agreement and Cohen's kappa. |
| Provider caching and savings | Measure returned usage and rerun evaluation after each optimization. |
| Self-host break-even | Requires the selected runtime's measured throughput and explicit economic inputs. |
| Reproducibility | Local execution and actual Colab execution are recorded separately. |

See [RUBRIC_EVIDENCE.md](RUBRIC_EVIDENCE.md), [EVALUATION_REPORT.md](EVALUATION_REPORT.md) and [BENCHMARKS.md](BENCHMARKS.md). A prepared experiment is not a completed measurement or a guaranteed grade. GitHub publication and submission await the owner's explicit instruction.

## Development files

The talabak directory contains the application; config contains model and notebook settings; data contains the fictional store and original evaluation cases; prompts contains versioned instructions; scripts contains evaluation and notebook tooling. These files support the one notebook.

## Attribution and design

The instructor explicitly permits borrowing patterns and infrastructure from [Murshid](https://github.com/MohammadYusif/llm-application-engineering/blob/de2ff3c0d8758c77d85c944e2d6f133647b84a91/capstone.qmd#L44-L50). Talabak uses that architectural approach with its own retail domain, tools, policy data, guards and evaluation cases. Course or student benchmark numbers are not reused as Talabak's results.

[Decisions](docs/DECISIONS.md) · [Dataset](docs/DATASET.md) · [Course](https://mohammadyusif.github.io/llm-application-engineering/) · [SDAIA Academy on GitHub](https://github.com/SDAIAAcademy)
