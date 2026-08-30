from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pymongo

from analysis.summarize_results import load_events, summarize
from experiments import (
    monotonic_reads,
    monotonic_writes,
    read_your_writes,
    writes_follow_reads,
)
from experiments.common import CONFIGS, JsonlRecorder, OperationServerListener, make_client


MODELS: dict[str, Callable[..., dict[str, Any]]] = {
    "read-your-writes": read_your_writes.run,
    "monotonic-reads": monotonic_reads.run,
    "monotonic-writes": monotonic_writes.run,
    "writes-follow-reads": writes_follow_reads.run,
}


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the S0 normal-operation baseline")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--seeds", default="20260830")
    parser.add_argument("--configs", default=",".join(CONFIGS))
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--label", default="pilot")
    parser.add_argument("--raw-dir", type=Path, default=Path("results/raw"))
    parser.add_argument("--summary-dir", type=Path, default=Path("results/summary"))
    args = parser.parse_args()

    if args.iterations <= 0:
        parser.error("--iterations must be positive")

    config_ids = parse_csv(args.configs)
    model_ids = parse_csv(args.models)
    seeds = [int(seed) for seed in parse_csv(args.seeds)]
    unknown_configs = sorted(set(config_ids) - CONFIGS.keys())
    unknown_models = sorted(set(model_ids) - MODELS.keys())
    if unknown_configs or unknown_models:
        parser.error(f"unknown configs={unknown_configs}, models={unknown_models}")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"baseline-s0-{args.label}-{timestamp}-{uuid.uuid4().hex[:8]}"
    raw_path = args.raw_dir / f"{run_id}.jsonl"
    summary_path = args.summary_dir / f"{run_id}.summary.json"

    suite_listener = OperationServerListener()
    probe_client = make_client(suite_listener)
    hello = probe_client.admin.command("hello")
    build_info = probe_client.admin.command("buildInfo")
    probe_client.close()

    started_wall = datetime.now(UTC)
    combination_results: list[dict[str, Any]] = []
    suite_failed = False

    with JsonlRecorder(raw_path) as recorder:
        recorder.write(
            {
                "event_kind": "suite_metadata",
                "run_id": run_id,
                "scenario": "S0-normal",
                "label": args.label,
                "started_at": started_wall.isoformat(),
                "iterations": args.iterations,
                "seeds": seeds,
                "configs": config_ids,
                "models": model_ids,
                "python_version": platform.python_version(),
                "pymongo_version": pymongo.version,
                "mongodb_version": build_info.get("version"),
                "replica_set": hello.get("setName"),
                "primary": hello.get("primary"),
                "hosts": sorted(hello.get("hosts", [])),
            }
        )

        for seed in seeds:
            for config_id in config_ids:
                for model_id in model_ids:
                    listener = OperationServerListener()
                    client = make_client(listener)
                    print(
                        f"START config={config_id} model={model_id} seed={seed}",
                        flush=True,
                    )
                    combination_started = time.monotonic()
                    try:
                        result = MODELS[model_id](
                            client=client,
                            listener=listener,
                            recorder=recorder,
                            config=CONFIGS[config_id],
                            run_id=run_id,
                            seed=seed,
                            iterations=args.iterations,
                        )
                        status = "ok" if result["errors"] == 0 else "completed-with-errors"
                        if result["errors"]:
                            suite_failed = True
                    except Exception as error:
                        status = "crashed"
                        result = {
                            "checks": 0,
                            "violations": 0,
                            "errors": 1,
                            "error_type": type(error).__name__,
                            "error_message": str(error),
                        }
                        suite_failed = True
                    finally:
                        client.close()

                    combination = {
                        "event_kind": "combination_summary",
                        "run_id": run_id,
                        "scenario": "S0-normal",
                        "config_id": config_id,
                        "model": model_id,
                        "seed": seed,
                        "status": status,
                        "duration_seconds": round(time.monotonic() - combination_started, 6),
                        **result,
                    }
                    recorder.write(combination)
                    combination_results.append(combination)
                    print(
                        f"END config={config_id} model={model_id} seed={seed} "
                        f"status={status} checks={result['checks']} "
                        f"violations={result['violations']} errors={result['errors']}",
                        flush=True,
                    )

    summary = summarize(load_events([raw_path]))
    summary["run_id"] = run_id
    summary["scenario"] = "S0-normal"
    summary["label"] = args.label
    summary["started_at"] = started_wall.isoformat()
    summary["finished_at"] = datetime.now(UTC).isoformat()
    summary["combination_results"] = combination_results
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(json.dumps({"raw": str(raw_path), "summary": str(summary_path)}, indent=2))
    print(json.dumps(summary["totals"], indent=2, sort_keys=True))
    return 1 if suite_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
