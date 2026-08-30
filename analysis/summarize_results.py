from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 6)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 6)


def load_events(paths: Iterable[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    events.append(json.loads(line))
    return events


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    aggregate_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    metadata = [event for event in events if event.get("event_kind") == "suite_metadata"]
    combination_results = [
        event for event in events if event.get("event_kind") == "combination_summary"
    ]
    for event in events:
        if event.get("event_kind") != "operation":
            continue
        groups[(event["config_id"], event["model"], int(event["seed"]))].append(event)
        aggregate_groups[(event["config_id"], event["model"])].append(event)

    def build_row(
        config_id: str,
        model: str,
        group: list[dict[str, Any]],
        seed: int | None = None,
    ) -> dict[str, Any]:
        latencies = [
            float(event["latency_ms"])
            for event in group
            if event.get("status") == "ok" and event.get("latency_ms") is not None
        ]
        check_events = [event for event in group if event.get("check")]
        violations = sum(int(event.get("violation_count", 0)) for event in check_events)
        errors = sum(1 for event in group if event.get("status") == "error")
        servers = Counter(
            event["served_by"] for event in group if event.get("served_by") is not None
        )
        row = {
            "config_id": config_id,
            "model": model,
            "operation_count": len(group),
            "check_count": len(check_events),
            "violation_count": violations,
            "violation_rate": round(violations / len(check_events), 8)
            if check_events
            else None,
            "error_count": errors,
            "success_rate": round((len(group) - errors) / len(group), 8),
            "latency_ms": {
                "p50": percentile(latencies, 0.50),
                "p95": percentile(latencies, 0.95),
                "p99": percentile(latencies, 0.99),
            },
            "served_by": dict(sorted(servers.items())),
        }
        if seed is not None:
            row["seed"] = seed
        else:
            row["seed_count"] = len({int(event["seed"]) for event in group})
        return row

    rows = [
        build_row(config_id, model, group, seed)
        for (config_id, model, seed), group in sorted(groups.items())
    ]
    aggregates = [
        build_row(config_id, model, group)
        for (config_id, model), group in sorted(aggregate_groups.items())
    ]

    result = {
        "metadata": metadata,
        "combination_results": combination_results,
        "groups": rows,
        "aggregates": aggregates,
        "totals": {
            "group_count": len(rows),
            "operation_count": sum(row["operation_count"] for row in rows),
            "check_count": sum(row["check_count"] for row in rows),
            "violation_count": sum(row["violation_count"] for row in rows),
            "error_count": sum(row["error_count"] for row in rows),
        },
    }
    if metadata:
        result["run_id"] = metadata[0].get("run_id")
        result["scenario"] = metadata[0].get("scenario")
        result["label"] = metadata[0].get("label")
        result["started_at"] = metadata[0].get("started_at")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = summarize(load_events(args.inputs))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
