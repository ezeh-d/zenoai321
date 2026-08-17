"""Run the consented Human Companion audio benchmark and write JSON evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent.voice.benchmarks import run_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path, help="JSONL manifest of consented WAV clips")
    parser.add_argument("--output", type=Path, help="Optional JSON result path")
    parser.add_argument("--allow-cloud-stt", action="store_true",
                        help="Run configured STT and WER; may use a billable provider")
    args = parser.parse_args()
    result = run_manifest(args.manifest, allow_stt=args.allow_cloud_stt)
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
