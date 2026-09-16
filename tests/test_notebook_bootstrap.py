"""Behavioral checks for honest, readable notebook setup; no provider calls."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import nbformat
import pytest

from scripts import build_notebook as builder


@pytest.fixture
def source_checkout(tmp_path):
    contents = {
        "requirements.txt": "example-package==1.2.3\n",
        "talabak/pipeline.py": "# Application source\n",
        "talabak/mock_gateway.py": "# Simulator source\n",
        "scripts/run_all.py": "# Evaluation entry point\n",
        "data/golden.v1.jsonl": '{}\n',
    }
    for name, text in contents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
    return tmp_path


def test_colab_without_public_source_stops_before_install_or_network(monkeypatch, source_checkout):
    manifest = builder.collect_manifest(source_checkout)
    source = builder.bootstrap_source(builder.read_submission(source_checkout), manifest)
    monkeypatch.setitem(sys.modules, "google.colab", SimpleNamespace())
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("No process may start"))
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: pytest.fail("No network lookup"))
    with pytest.raises(RuntimeError, match="NOT READY FOR COLAB"):
        exec(compile(source, "notebook-setup", "exec"), {})


def test_local_setup_uses_checkout_and_starts_only_after_source_verification(monkeypatch, source_checkout):
    manifest = builder.collect_manifest(source_checkout)
    source = builder.bootstrap_source(builder.read_submission(source_checkout), manifest)
    monkeypatch.delitem(sys.modules, "google.colab", raising=False)
    monkeypatch.chdir(source_checkout)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", "unused-test-cache")
    calls = []
    monkeypatch.setattr(builder, "ensure_dependencies", lambda root: calls.append(("dependencies", root)))
    monkeypatch.setattr(builder, "close_notebook_runtime", lambda ns: calls.append(("close", None)))

    def start(root):
        calls.append(("simulator", root))
        return SimpleNamespace(), "http://127.0.0.1:1/v1", {"routes": {}}, SimpleNamespace()

    monkeypatch.setattr(builder, "start_notebook_runtime", start)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("Local setup must not clone"))
    monkeypatch.setitem(sys.modules, "talabak_old_fixture", SimpleNamespace(
        __file__=str(source_checkout / "talabak/old_module.py"),
    ))
    namespace = {
        "RUN_ROOT": source_checkout,
        "close_notebook_runtime": lambda ns: calls.append(("old_close", None)),
    }
    exec(compile(source, "notebook-setup", "exec"), namespace)
    assert namespace["RUN_ROOT"] == source_checkout
    assert "talabak_old_fixture" not in sys.modules
    assert [name for name, _ in calls] == ["old_close", "close", "dependencies", "simulator"]
    assert namespace["source_manifest"]["sha256"] == manifest["sha256"]
    (source_checkout / "talabak/pipeline.py").write_text("# Changed since build\n", "utf-8")
    calls.clear()
    with pytest.raises(RuntimeError, match="Source differs"):
        exec(compile(source, "notebook-setup", "exec"), {})
    assert calls == [], "A changed source must not install dependencies or start the backend"


def test_matching_dependencies_require_no_install(monkeypatch, source_checkout):
    monkeypatch.setattr(builder.importlib.metadata, "version", lambda name: "1.2.3")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("Already pinned: no install needed"))
    assert builder.ensure_dependencies(source_checkout) is False


def test_missing_dependency_installs_pinned_requirements_and_propagates_failure(monkeypatch, source_checkout):
    def absent(name):
        raise builder.importlib.metadata.PackageNotFoundError(name)

    calls = []
    monkeypatch.setattr(builder.importlib.metadata, "version", absent)

    def fail_install(command, **kwargs):
        calls.append((command, kwargs))
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", fail_install)
    with pytest.raises(subprocess.CalledProcessError):
        builder.ensure_dependencies(source_checkout)
    assert calls[0][0][-2:] == ["-r", str(source_checkout / "requirements.txt")]
    assert calls[0][1]["check"] is True


@pytest.mark.parametrize("settings", [
    {"repository_url": "https://github.com/MohammadYusif/llm-application-engineering"},
    {"repository_url": "https://token@github.com/owner/project"},
    {"repository_url": "http://github.com/owner/project"},
    {"repository_url": "https://github.com/owner/project?token=secret"},
    {"revision": "main"},
    {"project_subdirectory": "../outside"},
    {"project_subdirectory": "C:/outside"},
])
def test_submission_locator_rejects_unpinned_or_misleading_sources(source_checkout, settings):
    config = source_checkout / "config/submission.json"
    config.parent.mkdir(exist_ok=True)
    config.write_text(json.dumps(settings), "utf-8")
    with pytest.raises(ValueError):
        builder.read_submission(source_checkout)


def test_setup_rerun_closes_prior_runtime_and_disables_stale_widgets():
    closed = []
    runtime = SimpleNamespace(close=lambda: closed.append("runtime"))
    store = SimpleNamespace(close=lambda: closed.append("store"))
    control = SimpleNamespace(disabled=False)
    namespace = {"_talabak_runtime": runtime, "chat_store": store, "send_button": control}
    builder.close_notebook_runtime(namespace)
    builder.close_notebook_runtime(namespace)
    assert closed == ["runtime", "store"]
    assert control.disabled is True
    assert namespace["chat_store"] is None


def test_generated_notebook_exposes_readable_source_and_has_no_hidden_payload(source_checkout, tmp_path):
    path = tmp_path / "review.ipynb"
    builder.build(source_checkout, path)
    notebook = nbformat.read(path, as_version=4)
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    combined = "\n".join(cell.source for cell in code_cells)
    assert "base64" not in combined and "SOURCE_BUNDLE" not in combined
    assert "zipfile" not in combined and "b64decode" not in combined
    assert max(len(line) for line in combined.splitlines()) < 180
    assert not any(cell.metadata.get("jupyter", {}).get("source_hidden") for cell in code_cells)
    assert not any("hide-input" in cell.metadata.get("tags", []) for cell in code_cells)
    assert "source_manifest" in notebook.metadata.talabak
    assert "bundle" not in notebook.metadata.talabak
    assert notebook.metadata.talabak.submission.colab_configured is False
    assert "RUN_LIVE = False" in combined
    assert "RUN_JUDGE_REVIEW = False" in combined
    assert "RUN_CACHE_BENCHMARK = False" in combined
    assert "RUN_SELF_HOST = False" in combined
    assert "RUN_BREAKEVEN = False" in combined


def test_publication_locator_changes_do_not_create_source_commit_hash_cycle(source_checkout):
    before = builder.collect_manifest(source_checkout)
    config = source_checkout / "config/submission.json"
    config.parent.mkdir(exist_ok=True)
    config.write_text(json.dumps({"repository_url": None, "revision": None}), "utf-8")
    after = builder.collect_manifest(source_checkout)
    assert before == after
    assert "config/submission.json" not in after["files"]
    runtime_profile = source_checkout / "runtime/models.live.json"
    runtime_profile.parent.mkdir()
    runtime_profile.write_text('{"routes": {}}', "utf-8")
    assert builder.collect_manifest(source_checkout) == before


@pytest.fixture
def live_notebook_cells(source_checkout, tmp_path):
    path = tmp_path / "live-controls.ipynb"
    builder.build(source_checkout, path)
    return [cell.source for cell in nbformat.read(path, as_version=4).cells if cell.cell_type == "code"]


@pytest.mark.parametrize("in_colab", [False, True])
def test_live_comparison_ignores_unused_judge_secret_auth(monkeypatch, tmp_path, live_notebook_cells, in_colab):
    from scripts import live_evaluate

    routes = {}
    for alias, mode in (("primary", "live_commercial"), ("open_weight", "live_open_weight")):
        routes[alias] = {
            "provider": "openai_compatible", "base_url": "https://provider.invalid/v1",
            "model": f"test-{alias}", "evidence_mode": mode,
            "auth": {"type": "env", "name": f"TEST_{alias.upper()}_KEY"},
            "capabilities": {"json_schema": True, "tools": True, "schema_with_tools": True,
                             "parallel_tool_calls": False,
                             "temperature": False, "token_parameter": "max_tokens"},
        }
    routes["open_weight"]["deployment"] = "hosted"
    routes["judge"] = {"auth": {"type": "secret", "name": "UNUSED_JUDGE_SECRET"}}
    config = {"routes": routes, "fallbacks": {}, "settings": {"max_output_tokens": 100}}
    profile = tmp_path / "live.json"
    profile.write_text(json.dumps(config), "utf-8")
    assert live_evaluate.preflight(config)["status"] == "READY_FOR_EXPLICIT_ENABLE"

    calls = []

    def compare(selected, **kwargs):
        calls.append((selected, kwargs))
        return {"status": "PILOT_COMPLETE"}

    monkeypatch.setattr(live_evaluate, "run_live_comparison", compare)
    forbidden = lambda name: pytest.fail("The unused judge must not load credentials")
    monkeypatch.setitem(sys.modules, "google.colab", SimpleNamespace(userdata=SimpleNamespace(get=forbidden)))
    source = next(cell for cell in live_notebook_cells if cell.startswith("RUN_LIVE = False"))
    source = source.replace("RUN_LIVE = False", "RUN_LIVE = True", 1)
    source = source.replace("LIVE_CONFIG_PATH = None", 'LIVE_CONFIG_PATH = "live.json"', 1)
    namespace = {"RUN_ROOT": tmp_path, "IN_COLAB": in_colab, "json": json}
    exec(compile(source, "notebook-live-comparison", "exec"), namespace)
    assert len(calls) == 1
    assert calls[0][1]["secret_loader"] is None
    assert calls[0][1]["enabled"] is True
    assert namespace["live_result"]["status"] == "PILOT_COMPLETE"


def test_enabled_judge_resolves_its_own_colab_secret_loader(monkeypatch, tmp_path, live_notebook_cells):
    from scripts import prepare_review
    from talabak import llm

    review_dir = tmp_path / "human-review"
    review_dir.mkdir()
    (review_dir / "review_manifest.json").write_text('{"paths": {}}', "utf-8")
    loader = lambda name: "synthetic-test-secret"
    monkeypatch.setitem(sys.modules, "google.colab", SimpleNamespace(userdata=SimpleNamespace(get=loader)))
    calls = []
    closed = []

    def client(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(close=lambda: closed.append(True))

    monkeypatch.setattr(llm, "SDKClient", client)
    monkeypatch.setattr(prepare_review, "judge_review", lambda *args, **kwargs: {"status": "TEST_ONLY"})
    source = next(cell for cell in live_notebook_cells if cell.startswith("RUN_JUDGE_REVIEW = False"))
    source = source.replace("RUN_JUDGE_REVIEW = False", "RUN_JUDGE_REVIEW = True", 1)
    namespace = {
        "RUN_LIVE": True, "IN_COLAB": True, "Path": Path, "json": json,
        "live_result": {"status": "LIVE_COMPLETE", "run_dir": str(tmp_path)},
        "live_config": {"routes": {
            "primary": {"auth": {"type": "env", "name": "TEST_PRIMARY_KEY"}},
            "judge": {"auth": {"type": "secret", "name": "TEST_JUDGE_SECRET"}},
        }},
        "secret_loader": None,
    }
    exec(compile(source, "notebook-live-judge", "exec"), namespace)
    assert len(calls) == 1
    assert calls[0]["secret_loader"] is loader
    assert calls[0]["allow_live"] is True
    assert set(calls[0]["config"]["routes"]) == {"judge"}
    assert closed == [True]


@pytest.mark.parametrize("auth_type", ["env", "secret"])
def test_self_host_uses_separate_profile_and_only_its_credentials(
        monkeypatch, tmp_path, live_notebook_cells, auth_type):
    from scripts import live_benchmark

    profile = {"routes": {
        "open_weight": {"model": "self-host-test-model", "deployment": "self_hosted",
                        "auth": {"type": auth_type, "name": "TEST_SELF_HOST_KEY"}},
        "judge": {"auth": {"type": "secret", "name": "UNUSED_JUDGE_SECRET"}},
    }, "fallbacks": {"open_weight": ["judge"]}}
    (tmp_path / "self-host.json").write_text(json.dumps(profile), "utf-8")
    loader = lambda name: "synthetic-test-secret"
    monkeypatch.setitem(sys.modules, "google.colab", SimpleNamespace(userdata=SimpleNamespace(get=loader)))
    calls = []

    def measure(config, **kwargs):
        calls.append((config, kwargs))
        return {"status": "TEST_ONLY"}

    monkeypatch.setattr(live_benchmark, "measure_self_host", measure)
    source = next(cell for cell in live_notebook_cells if cell.startswith("RUN_CACHE_BENCHMARK = False"))
    source = source.replace("RUN_SELF_HOST = False", "RUN_SELF_HOST = True", 1)
    source = source.replace("SELF_HOST_CONFIG_PATH = None", 'SELF_HOST_CONFIG_PATH = "self-host.json"', 1)
    namespace = {
        "RUN_LIVE": True, "IN_COLAB": auth_type == "secret", "RUN_ROOT": tmp_path, "json": json,
        "live_config": {"routes": {"open_weight": {"model": "hosted-comparison-model"}}},
        "secret_loader": None,
    }
    exec(compile(source, "notebook-self-host", "exec"), namespace)
    assert len(calls) == 1
    selected, options = calls[0]
    assert set(selected["routes"]) == {"open_weight"}
    assert selected["routes"]["open_weight"]["model"] == "self-host-test-model"
    assert selected["fallbacks"] == {"open_weight": []}
    assert options["secret_loader"] is (loader if auth_type == "secret" else None)
    assert options["enabled"] is True


def test_self_host_without_selected_profile_stops_before_measurement(monkeypatch, tmp_path, live_notebook_cells):
    from scripts import live_benchmark

    monkeypatch.setattr(live_benchmark, "measure_self_host", lambda *a, **k: pytest.fail("Profile required first"))
    source = next(cell for cell in live_notebook_cells if cell.startswith("RUN_CACHE_BENCHMARK = False"))
    source = source.replace("RUN_SELF_HOST = False", "RUN_SELF_HOST = True", 1)
    with pytest.raises(RuntimeError, match="Select a separate self-host deployment profile"):
        exec(compile(source, "notebook-self-host-unconfigured", "exec"), {"RUN_LIVE": True})
