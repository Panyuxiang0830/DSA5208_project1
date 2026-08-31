from __future__ import annotations

import argparse
import json
import os
import threading
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from analysis.summarize_results import load_events, percentile, summarize
from experiments.common import (
    CONFIGS,
    JsonlRecorder,
    OperationServerListener,
    configured_collection,
    error_details,
    logical_session,
    make_client,
    new_operation_id,
    operation_event,
    validation_collection,
)


MODEL = "read-your-writes-transition"


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def transition_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_config: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("event_kind") != "operation":
            continue
        config_id = str(event["config_id"])
        phase = str(event.get("phase_at_start", "unknown"))
        grouped[(config_id, phase)].append(event)
        by_config[config_id].append(event)

    phase_rows: list[dict[str, Any]] = []
    for (config_id, phase), group in sorted(grouped.items()):
        errors = sum(event.get("status") == "error" for event in group)
        checks = [event for event in group if event.get("check")]
        violations = sum(int(event.get("violation_count", 0)) for event in checks)
        successful_latencies = [
            float(event["latency_ms"])
            for event in group
            if event.get("status") == "ok" and event.get("latency_ms") is not None
        ]
        phase_rows.append(
            {
                "config_id": config_id,
                "phase": phase,
                "operation_count": len(group),
                "error_count": errors,
                "error_rate": round(errors / len(group), 8) if group else None,
                "check_count": len(checks),
                "violation_count": violations,
                "latency_ms": {
                    "p50": percentile(successful_latencies, 0.50),
                    "p95": percentile(successful_latencies, 0.95),
                    "p99": percentile(successful_latencies, 0.99),
                },
            }
        )

    recovery_rows: list[dict[str, Any]] = []
    for config_id, group in sorted(by_config.items()):
        successful = sorted(
            (
                event
                for event in group
                if event.get("status") == "ok" and event.get("operation") == "write"
            ),
            key=lambda event: float(event.get("elapsed_end_ms", 0)),
        )
        after_fault = [
            event for event in successful if event.get("phase_at_end") != "pre-fault"
        ]
        after_election = [
            event for event in successful if event.get("phase_at_end") == "post-election"
        ]
        recovery_rows.append(
            {
                "config_id": config_id,
                "first_successful_write_after_fault_elapsed_ms": (
                    after_fault[0].get("elapsed_end_ms") if after_fault else None
                ),
                "first_successful_write_after_election_elapsed_ms": (
                    after_election[0].get("elapsed_end_ms") if after_election else None
                ),
            }
        )

    return {"phase_rows": phase_rows, "recovery_rows": recovery_rows}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Continuously run RYW pairs across a Primary election window"
    )
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--duration-seconds", type=float, default=25.0)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--configs", default=",".join(CONFIGS))
    parser.add_argument("--label", default="pilot")
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--fault-marker", type=Path, required=True)
    parser.add_argument("--elected-marker", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, default=Path("results/raw"))
    parser.add_argument("--summary-dir", type=Path, default=Path("results/summary"))
    args = parser.parse_args()

    if args.duration_seconds <= 0:
        parser.error("--duration-seconds must be positive")

    config_ids = parse_csv(args.configs)
    unknown = sorted(set(config_ids) - CONFIGS.keys())
    if unknown:
        parser.error(f"unknown configs={unknown}")

    os.environ["EXPERIMENT_SCENARIO"] = args.scenario
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    scenario_slug = "".join(
        character.lower() if character.isalnum() else "-"
        for character in args.scenario
    ).strip("-")
    run_id = f"{scenario_slug}-{args.label}-{timestamp}-{uuid.uuid4().hex[:8]}"
    raw_path = args.raw_dir / f"{run_id}.jsonl"
    summary_path = args.summary_dir / f"{run_id}.summary.json"

    for marker in (args.ready_file, args.fault_marker, args.elected_marker):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.unlink(missing_ok=True)

    resources: list[tuple[str, Any, Any, OperationServerListener, str]] = []
    for config_id in config_ids:
        listener = OperationServerListener()
        client = make_client(listener, timeout_ms=1500)
        collection_name = "transition_window"
        collection = configured_collection(client, CONFIGS[config_id], collection_name)
        key = f"{run_id}:{config_id}:{args.seed}"
        validation_collection(client, collection_name).replace_one(
            {"_id": key}, {"_id": key, "version": 0}, upsert=True
        )
        resources.append((config_id, client, collection, listener, key))

    started_ns = time.monotonic_ns()
    deadline_ns = started_ns + int(args.duration_seconds * 1_000_000_000)
    results: dict[str, dict[str, int]] = {}

    def phase() -> str:
        if not args.fault_marker.exists():
            return "pre-fault"
        if not args.elected_marker.exists():
            return "election"
        return "post-election"

    def worker(
        config_id: str,
        client: Any,
        collection: Any,
        listener: OperationServerListener,
        key: str,
        recorder: JsonlRecorder,
    ) -> None:
        config = CONFIGS[config_id]
        version = 0
        checks = 0
        violations = 0
        errors = 0
        try:
            with logical_session(client, config) as session:
                while time.monotonic_ns() < deadline_ns:
                    version += 1
                    write_id = new_operation_id("transition-write")
                    write_started = time.monotonic_ns()
                    phase_started = phase()
                    try:
                        collection.replace_one(
                            {"_id": key},
                            {
                                "_id": key,
                                "version": version,
                                "writer_id": f"transition-{config_id}",
                            },
                            upsert=True,
                            session=session,
                            comment=write_id,
                        )
                        write_ended = time.monotonic_ns()
                        recorder.write(
                            operation_event(
                                run_id=run_id,
                                config=config,
                                model=MODEL,
                                seed=args.seed,
                                iteration=version,
                                operation_id=write_id,
                                operation="write",
                                started_ns=write_started,
                                ended_ns=write_ended,
                                status="ok",
                                listener=listener,
                                phase_at_start=phase_started,
                                phase_at_end=phase(),
                                elapsed_start_ms=round(
                                    (write_started - started_ns) / 1_000_000, 6
                                ),
                                elapsed_end_ms=round(
                                    (write_ended - started_ns) / 1_000_000, 6
                                ),
                                written_version=version,
                            )
                        )
                    except Exception as error:
                        write_ended = time.monotonic_ns()
                        errors += 1
                        recorder.write(
                            operation_event(
                                run_id=run_id,
                                config=config,
                                model=MODEL,
                                seed=args.seed,
                                iteration=version,
                                operation_id=write_id,
                                operation="write",
                                started_ns=write_started,
                                ended_ns=write_ended,
                                status="error",
                                listener=listener,
                                phase_at_start=phase_started,
                                phase_at_end=phase(),
                                elapsed_start_ms=round(
                                    (write_started - started_ns) / 1_000_000, 6
                                ),
                                elapsed_end_ms=round(
                                    (write_ended - started_ns) / 1_000_000, 6
                                ),
                                **error_details(error),
                            )
                        )
                        time.sleep(0.02)
                        continue

                    read_id = new_operation_id("transition-read")
                    read_started = time.monotonic_ns()
                    phase_started = phase()
                    try:
                        document = collection.find_one(
                            {"_id": key}, session=session, comment=read_id
                        )
                        read_ended = time.monotonic_ns()
                        observed = document.get("version", -1) if document else -1
                        violation = int(observed < version)
                        checks += 1
                        violations += violation
                        recorder.write(
                            operation_event(
                                run_id=run_id,
                                config=config,
                                model=MODEL,
                                seed=args.seed,
                                iteration=version,
                                operation_id=read_id,
                                operation="read-after-write",
                                started_ns=read_started,
                                ended_ns=read_ended,
                                status="ok",
                                listener=listener,
                                check=True,
                                violation_count=violation,
                                phase_at_start=phase_started,
                                phase_at_end=phase(),
                                elapsed_start_ms=round(
                                    (read_started - started_ns) / 1_000_000, 6
                                ),
                                elapsed_end_ms=round(
                                    (read_ended - started_ns) / 1_000_000, 6
                                ),
                                expected_min_version=version,
                                observed_version=observed,
                            )
                        )
                    except Exception as error:
                        read_ended = time.monotonic_ns()
                        errors += 1
                        recorder.write(
                            operation_event(
                                run_id=run_id,
                                config=config,
                                model=MODEL,
                                seed=args.seed,
                                iteration=version,
                                operation_id=read_id,
                                operation="read-after-write",
                                started_ns=read_started,
                                ended_ns=read_ended,
                                status="error",
                                listener=listener,
                                check=True,
                                phase_at_start=phase_started,
                                phase_at_end=phase(),
                                elapsed_start_ms=round(
                                    (read_started - started_ns) / 1_000_000, 6
                                ),
                                elapsed_end_ms=round(
                                    (read_ended - started_ns) / 1_000_000, 6
                                ),
                                **error_details(error),
                            )
                        )
                    time.sleep(0.01)
        finally:
            results[config_id] = {
                "checks": checks,
                "violations": violations,
                "errors": errors,
            }
            client.close()

    with JsonlRecorder(raw_path) as recorder:
        recorder.write(
            {
                "event_kind": "suite_metadata",
                "run_id": run_id,
                "scenario": args.scenario,
                "label": args.label,
                "seed": args.seed,
                "duration_seconds": args.duration_seconds,
                "configs": config_ids,
                "started_at": datetime.now(UTC).isoformat(),
            }
        )
        threads = [
            threading.Thread(
                target=worker,
                args=(*resource, recorder),
                name=f"transition-{resource[0]}",
            )
            for resource in resources
        ]
        for thread in threads:
            thread.start()
        args.ready_file.touch()
        for thread in threads:
            thread.join()

    events = load_events([raw_path])
    summary = summarize(events)
    summary.update(transition_summary(events))
    summary.update(
        {
            "run_id": run_id,
            "scenario": args.scenario,
            "label": args.label,
            "seed": args.seed,
            "duration_seconds": args.duration_seconds,
            "worker_results": results,
        }
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"raw": str(raw_path), "summary": str(summary_path)}, indent=2))
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
