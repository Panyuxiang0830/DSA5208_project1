from __future__ import annotations

import time
from typing import Any

from .common import (
    ExperimentConfig,
    JsonlRecorder,
    OperationServerListener,
    configured_collection,
    error_details,
    logical_session,
    new_operation_id,
    operation_event,
    validation_collection,
    wait_for_majority_version,
)


MODEL = "monotonic-writes"


def run(
    *,
    client: Any,
    listener: OperationServerListener,
    recorder: JsonlRecorder,
    config: ExperimentConfig,
    run_id: str,
    seed: int,
    iterations: int,
) -> dict[str, Any]:
    collection_name = "monotonic_writes"
    collection = configured_collection(client, config, collection_name)
    validator = validation_collection(client, collection_name)
    key = f"{run_id}:{config.config_id}:{seed}"
    validator.replace_one(
        {"_id": key}, {"_id": key, "version": 0, "history": []}, upsert=True
    )

    errors = 0
    acknowledged: list[int] = []

    with logical_session(client, config) as session:
        for iteration in range(1, iterations + 1):
            operation_id = new_operation_id("mw-write")
            started = time.monotonic_ns()
            try:
                collection.update_one(
                    {"_id": key},
                    {
                        "$set": {"version": iteration, "writer_id": "mw-client-1"},
                        "$push": {"history": iteration},
                    },
                    session=session,
                    comment=operation_id,
                )
                ended = time.monotonic_ns()
                acknowledged.append(iteration)
                recorder.write(
                    operation_event(
                        run_id=run_id,
                        config=config,
                        model=MODEL,
                        seed=seed,
                        iteration=iteration,
                        operation_id=operation_id,
                        operation="ordered-write",
                        started_ns=started,
                        ended_ns=ended,
                        status="ok",
                        listener=listener,
                        written_version=iteration,
                    )
                )
            except Exception as error:
                ended = time.monotonic_ns()
                errors += 1
                recorder.write(
                    operation_event(
                        run_id=run_id,
                        config=config,
                        model=MODEL,
                        seed=seed,
                        iteration=iteration,
                        operation_id=operation_id,
                        operation="ordered-write",
                        started_ns=started,
                        ended_ns=ended,
                        status="error",
                        listener=listener,
                        **error_details(error),
                    )
                )

    validation_id = new_operation_id("mw-validation")
    started = time.monotonic_ns()
    document = wait_for_majority_version(validator, key, acknowledged[-1] if acknowledged else 0)
    ended = time.monotonic_ns()
    history = document.get("history", []) if document else []
    expected = acknowledged
    mismatch_count = sum(1 for left, right in zip(history, expected) if left != right)
    mismatch_count += abs(len(history) - len(expected))
    final_version = document.get("version", -1) if document else -1
    if acknowledged and final_version != acknowledged[-1]:
        mismatch_count += 1

    recorder.write(
        operation_event(
            run_id=run_id,
            config=config,
            model=MODEL,
            seed=seed,
            iteration=iterations,
            operation_id=validation_id,
            operation="validate-write-order",
            started_ns=started,
            ended_ns=ended,
            status="ok",
            listener=listener,
            check=True,
            violation_count=mismatch_count,
            acknowledged_versions=acknowledged,
            observed_history=history,
            final_version=final_version,
        )
    )

    return {"checks": 1, "violations": mismatch_count, "errors": errors}
