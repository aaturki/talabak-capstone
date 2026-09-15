# Notebook setup and source fidelity

## Current status

The notebook imports ordinary project files. It no longer carries an encoded application archive or hides the setup cell. The first cell records a source digest and starts the default no-key simulator after checking the checkout and dependencies.

`config/submission.json` currently has no repository URL or source revision. This is intentional: publication has not been authorized and no project URL has been supplied. Local review works from the existing checkout. A fresh Colab session stops with **NOT READY FOR COLAB**, before cloning, package installation or model calls. That stop is not described as successful Colab reproduction.

## Local review

Open `Talabak_Capstone.ipynb` from the Talabak project directory and run all cells. The setup can also find `outputs/talabak` when launched from the current task workspace. It checks source hashes, installs only missing or mismatched pinned dependencies, and starts a loopback simulator on an available port.

The notebook calls the same application, tests and evaluation scripts as the project. Simulator results are labelled accordingly. The tests do not need provider credentials. Rerunning setup closes its prior runtime, closes demonstration stores, disables old conversation buttons and clears imports loaded from the previous project directory before loading the current files.

## Configure the final Colab source after authorization

The fields are:

| Field | Meaning |
|---|---|
| `repository_url` | The owner's actual public HTTPS GitHub repository. No credentials or query parameters belong here. |
| `revision` | The immutable, 40-character lowercase SHA of the reviewed source commit. A moving branch name is rejected. |
| `project_subdirectory` | The application directory inside that repository; `.` if it is the repository root. |

Commit the reviewed application source first. Set this locator to that source commit, rebuild the notebook, and publish the notebook when authorized. The locator is excluded from the application-source digest to avoid a commit having to contain its own hash; its exact values are separately recorded in notebook metadata and visible in setup. This supports a notebook commit referring to an earlier immutable source commit.

In Colab, setup clones that repository and checks out the configured commit. An existing checkout at a different commit is rejected without deleting or overwriting it; start a fresh runtime to use the pinned source. The current notebook must then pass **Runtime → Run all** in that fresh Colab environment before claiming Colab reproduction.

## Source manifest

The builder's `collect_manifest(root)` records every included source path and SHA-256 in notebook metadata, plus a digest of that mapping. Setup recomputes the mapping and stops before evaluation when it differs. Ordinary application modules, scripts, tests, prompt files, configuration and documentation are included.

Generated notebooks, rendered previews, reports, run artifacts, caches, local databases and secret files are excluded. `config/submission.json` is the separately recorded publication locator, as explained above. No source bytes or archive are put in the manifest.

Rebuild the notebook after a reviewed source change. Building validates notebook structure but does not run tests or claim execution. Saved execution records must be refreshed after a successful fresh-kernel run; older evidence cannot establish success of a changed notebook.

## Optional live sections

`RUN_LIVE`, `RUN_JUDGE_REVIEW`, `RUN_CACHE_BENCHMARK`, `RUN_SELF_HOST` and `RUN_BREAKEVEN` default to `False`. The live configuration path and economic assumptions are unset. The default conversation remains a no-key simulator.

When authorized access is available, place the completed live configuration at `runtime/models.live.json`, select that path and explicitly enable the intended experiment. The runtime profile is excluded from the default source manifest; the live runner records its own configuration provenance. This prevents a local provider choice from changing the notebook's default-source identity. Credentials stay in named environment variables or Colab Secrets. Colab Secrets are accessed only inside the enabled live path for configuration entries using secret-based authentication. An unconfigured example is not a working provider connection.

The comparison runner evaluates the same application and selected dataset on both live backends. Limited runs remain pilots. A human-review packet contains genuine saved model answers and blank labels; preparing it or generating judge predictions does not establish human calibration. Existing review files are preserved when their cell is rerun. After human labeling, the separate scoring cell accepts a review directory and completed CSV; it makes no model calls and validates answer-version bindings before reporting calibration. See `LIVE_EVALUATION.md` for the review format.

The comparison resolves credentials only for `primary` and `open_weight`. Judge credentials are resolved separately only when judge review is enabled; an unused judge secret cannot block a local comparison using environment authentication.

Cache and self-host experiments require their own telemetry and deployment evidence. For throughput, select a separate `SELF_HOST_CONFIG_PATH`, such as `runtime/models.self-host.json`, with an `open_weight` route identifying your actual deployment (`deployment: self_hosted`). The notebook selects only this route, disables fallbacks, and resolves its credentials independently. For a gateway-versus-self-host break-even comparison, the comparison profile's open-weight route must identify a hosted gateway (`deployment: hosted`); it can use a different endpoint for the same model. Break-even calculation requires matched complete live runs and documented economic assumptions. See `LIVE_MEASUREMENTS.md` for measurement limits and required inputs.

The conversation widget contains only message entry, Send and New session. Provider configuration, measurement flags and review administration stay in the engineering sections.
