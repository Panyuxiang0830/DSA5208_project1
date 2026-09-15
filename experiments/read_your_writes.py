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
    read_max_time_ms,
    resolve_read_collections,
    validation_collection,
)


MODEL = "read-your-writes"


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
    collection_name = "read_your_writes"
    collection = configured_collection(client, config, collection_name)
    validator = validation_collection(client, collection_name)
    key = f"{run_id}:{config.config_id}:{seed}"
    validator.replace_one({"_id": key}, {"_id": key, "version": 0}, upsert=True)

    direct_clients, read_collections = resolve_read_collections(
        client, listener, config, collection_name, collection
    )
    max_time_ms = read_max_time_ms(config)

    violations = 0
    errors = 0
    checks = 0

    try:
        with logical_session(client, config) as session:
            for iteration in range(1, iterations + 1):
                write_id = new_operation_id("ryw-write")
                started = time.monotonic_ns()
                try:
                    collection.replace_one(
                        {"_id": key},
                        {
                            "_id": key,
                            "version": iteration,
                            "writer_id": "ryw-client-1",
                            "operation_id": write_id,
                        },
                        upsert=True,
                        session=session,
                        comment=write_id,
                    )
                    ended = time.monotonic_ns()
                    recorder.write(
                        operation_event(
                            run_id=run_id,
                            config=config,
                            model=MODEL,
                            seed=seed,
                            iteration=iteration,
                            operation_id=write_id,
                            operation="write",
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
                            operation_id=write_id,
                            operation="write",
                            started_ns=started,
                            ended_ns=ended,
                            status="error",
                            listener=listener,
                            **error_details(error),
                        )
                    )
                    continue

                read_id = new_operation_id("ryw-read")
                started = time.monotonic_ns()
                try:
                    read_collection = read_collections[(iteration - 1) % len(read_collections)]
                    document = read_collection.find_one(
                        {"_id": key},
                        session=session,
                        comment=read_id,
                        max_time_ms=max_time_ms,
                    )
                    ended = time.monotonic_ns()
                    observed = document.get("version", -1) if document else -1
                    violation = int(observed < iteration)
                    violations += violation
                    checks += 1
                    recorder.write(
                        operation_event(
                            run_id=run_id,
                            config=config,
                            model=MODEL,
                            seed=seed,
                            iteration=iteration,
                            operation_id=read_id,
                            operation="read-after-write",
                            started_ns=started,
                            ended_ns=ended,
                            status="ok",
                            listener=listener,
                            check=True,
                            violation_count=violation,
                            expected_min_version=iteration,
                            observed_version=observed,
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
                            operation_id=read_id,
                            operation="read-after-write",
                            started_ns=started,
                            ended_ns=ended,
                            status="error",
                            listener=listener,
                            check=True,
                            **error_details(error),
                        )
                    )
    finally:
        for direct in direct_clients:
            direct.close()

    return {"checks": checks, "violations": violations, "errors": errors}
