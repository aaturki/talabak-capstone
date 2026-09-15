"""Measure local simulator component tokens, without claiming live context capacity."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import tiktoken


ROOT = Path(__file__).resolve().parents[1]


def measure(root: Path = ROOT) -> dict:
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(root / "config/tokenizer_cache"))
    tokenizer = tiktoken.get_encoding("o200k_base")
    settings = json.loads((root / "config/models.json").read_text("utf-8"))["settings"]
    components = []
    prompt_files = [path for path in sorted((root / "prompts").iterdir()) if path.is_file() and path.suffix in {".md", ".json"}]
    for path in prompt_files + [root / "data/store.v1.json"]:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        components.append({"path": str(path.relative_to(root)).replace("\\", "/"),
                           "tokens": len(tokenizer.encode(text)), "utf8_bytes": len(raw),
                           "sha256": hashlib.sha256(raw).hexdigest()})
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from talabak.schemas import tool_definitions
    rendered_tools = json.dumps(tool_definitions(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    tool_schema_tokens = len(tokenizer.encode(rendered_tools))
    return {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "evidence_mode": "local_tokenizer_component_measurement",
            "tokenizer": "o200k_base", "max_output_tokens": settings["max_output_tokens"],
            "components": components,
            "rendered_tool_definitions_tokens": tool_schema_tokens,
            "rendered_tool_definitions_sha256": hashlib.sha256(rendered_tools.encode()).hexdigest(),
            "all_files_token_sum": sum(row["tokens"] for row in components),
            "limitations": ["The all-files sum is inventory, not a claim that every file is sent together.",
                            "Wire messages, tool schemas and serialization overhead are measured by actual gateway usage.",
                            "No live model context-window or performance claim is made."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/context_budget.json")
    args = parser.parse_args()
    report = measure()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
