# Break-even inputs — not yet measured

`scripts/breakeven.py` is ready to calculate economics from an actual self-hosted load measurement. No live model has been run for this measurement, and no actual commercial tariff or hardware cost has been supplied. Running without an input file returns **NOT_MEASURED** and invents no default numbers. Tests use synthetic arithmetic examples only; they are not project results.

```powershell
python -X utf8 scripts/breakeven.py
python -X utf8 scripts/breakeven.py --input work/live_breakeven_inputs.json --out eval/out/live_breakeven.json
```

The calculator makes no network requests, reads no key and performs no price lookup. Changing an evidence label to `live` is insufficient: the caller must supply a real measurement artifact, and the reviewer must verify its origin.

## JSON input fields

The root contains `schema_version="breakeven-v1"` and three objects: `self_host_measurement`, `assumptions` and `routes`.

### self_host_measurement

| Field | Required input |
|---|---|
| `evidence_mode` | `live`; `simulator` is rejected |
| `measurement_kind` | `self_hosted_load`; serial API latency does not measure self-hosted hardware capacity |
| `traffic_sha256` | Hash of identical test traffic used across the comparisons |
| `source_artifact_sha256` | Hash of the original measurement record |
| `hardware`, `model_id` | Actual hardware description and model identifier |
| `measured_at` | ISO timestamp including a timezone |
| `concurrency`, `batch_size` | Concurrency and batch size used during measurement |
| `saturation_observed` | Whether hardware saturation was observed; `false` means the run does not establish maximum capacity |
| `totals` or `windows` | Exactly one of the two forms described below |

`totals` contains measured `completed_requests`, `attempted_requests` and `elapsed_seconds`. The denominator is elapsed wall-clock time, not the sum of overlapping request latencies.

`windows` contains intervals with `started_at`, `ended_at`, `completed_requests` and `attempted_requests`. Overlapping intervals are rejected to avoid double-counting time or capacity. Throughput is total completed requests divided by total interval duration. Review request failures and answer quality too; an HTTP completion does not establish a useful answer.

### assumptions

Supply every number explicitly; there are no default economic assumptions: `monthly_fixed_usd`, `variable_usd_per_request`, `available_hours_per_month` (up to 744), `planned_utilization` (0 to 1), and `basis` describing the sources of these assumptions. Account for hardware, hosting, electricity, operations, redundancy and idle time without double counting.

### routes

Supply **both routes**, `commercial` and `open_weight_gateway`. Each requires:

- `evidence_mode="live"` and the same `traffic_sha256` as the self-host measurement.
- `source_artifact_sha256`, `model_id` and `measured_requests`.
- `cost_usd_per_request` measured or calculated from actual usage and a documented tariff, with `cost_basis` explaining the calculation and tariff date. Illustrative simulator tariffs are not admissible.

## Calculation and limits

At monthly volume N, self-host cost is F + vN and the comparison route costs cN. When c > v, break-even volume is F/(c-v). The calculator reports the first whole request count achieving parity and the first achieving a strict saving. When self-host variable cost exceeds the comparison route's cost, positive fixed cost cannot be recovered. It also handles equal costs, zero utilization and a break-even volume that exceeds measured capacity.

Monthly capacity projects the measured completed-request rate across the supplied operating hours. It is not a month-long measurement or a service guarantee. The report compares commercial and hosted open-weight routes separately, showing when self-hosting is cheaper than one but more expensive than the other. The presence of this calculator does not establish a capstone measurement; actual runs and reviewable sources are still required.
