from __future__ import annotations

import random
import threading
import time
from typing import Any

from .common import (
    ExperimentConfig,
    JsonlRecorder,
    OperationServerListener,
    configured_collection,
    direct_secondary_collections,
    error_details,
    logical_session,
    new_operation_id,
    operation_event,
    validation_collection,
    wait_for_majority_version,
)


MODEL = "writes-follow-reads"


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
    collection_name = "writes_follow_reads"
    collection = configured_collection(client, config, collection_name)
    validator = validation_collection(client, collection_name)
    key = f"{run_id}:{config.config_id}:{seed}"
    validator.replace_one(
        {"_id": key}, {"_id": key, "version": 0, "dependents": []}, upsert=True
    )

    direct_clients: list[Any] = []
    read_collections = [collection]
    if config.directed_secondary_reads:
        direct_clients, read_collections = direct_secondary_collections(
            client, listener, config, collection_name
        )

    writer_errors: list[Exception] = []
    writer_random = random.Random(seed ^ 0xA5A5)

    def background_writer() -> None:
        for version in range(1, iterations * 2 + 1):
            operation_id = new_operation_id("wfr-background-write")
            started = time.monotonic_ns()
            try:
                collection.update_one(
                    {"_id": key},
                    {"$max": {"version": version}},
                    comment=operation_id,
                )
                ended = time.monotonic_ns()
                recorder.write(
                    operation_event(
                        run_id=run_id,
                        config=config,
                        model=MODEL,
                        seed=seed,
                        iteration=version,
                        operation_id=operation_id,
                        operation="background-write",
                        started_ns=started,
                        ended_ns=ended,
                        status="ok",
                        listener=listener,
                        written_version=version,
                    )
                )
            except Exception as error:
                ended = time.monotonic_ns()
                writer_errors.append(error)
                recorder.write(
                    operation_event(
                        run_id=run_id,
                        config=config,
                        model=MODEL,
                        seed=seed,
                        iteration=version,
                        operation_id=operation_id,
                        operation="background-write",
                        started_ns=started,
                        ended_ns=ended,
                        status="error",
                        listener=listener,
                        **error_details(error),
                    )
                )
                return
            time.sleep(writer_random.uniform(0.0002, 0.0015))

    writer = threading.Thread(target=background_writer, name="wfr-writer", daemon=True)
    writer.start()

    violations = 0
    errors = 0
    checks = 0
    acknowledged_dependents: list[int] = []

    try:
        with logical_session(client, config) as session:
            for iteration in range(1, iterations + 1):
                read_id = new_operation_id("wfr-read")
                started = time.monotonic_ns()
                try:
                    read_collection = read_collections[(iteration - 1) % len(read_collections)]
                    document = read_collection.find_one(
                        {"_id": key}, session=session, comment=read_id
                    )
                    ended = time.monotonic_ns()
                    parent_version = document.get("version", -1) if document else -1
                    recorder.write(
                        operation_event(
                            run_id=run_id,
                            config=config,
                            model=MODEL,
                            seed=seed,
                            iteration=iteration,
                            operation_id=read_id,
                            operation="causal-read",
                            started_ns=started,
                            ended_ns=ended,
                            status="ok",
                            listener=listener,
                            observed_version=parent_version,
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
                            operation="causal-read",
                            started_ns=started,
                            ended_ns=ended,
                            status="error",
                            listener=listener,
                            **error_details(error),
                        )
                    )
                    continue

                write_id = new_operation_id("wfr-dependent-write")
                started = time.monotonic_ns()
                try:
                    result = collection.update_one(
                        {"_id": key, "version": {"$gte": parent_version}},
                        {
                            "$push": {
                                "dependents": {
                                    "sequence": iteration,
                                    "parent_version": parent_version,
                                    "read_operation_id": read_id,
                                    "write_operation_id": write_id,
                                }
                            }
                        },
                        session=session,
                        comment=write_id,
                    )
                    ended = time.monotonic_ns()
                    violation = int(parent_version < 0 or result.matched_count != 1)
                    violations += violation
                    checks += 1
                    if not violation:
                        acknowledged_dependents.append(iteration)
                    recorder.write(
                        operation_event(
                            run_id=run_id,
                            config=config,
                            model=MODEL,
                            seed=seed,
                            iteration=iteration,
                            operation_id=write_id,
                            operation="dependent-write",
                            started_ns=started,
                            ended_ns=ended,
                            status="ok",
                            listener=listener,
                            check=True,
                            violation_count=violation,
                            parent_version=parent_version,
                            matched_count=result.matched_count,
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
                            operation="dependent-write",
                            started_ns=started,
                            ended_ns=ended,
                            status="error",
                            listener=listener,
                            check=True,
                            parent_version=parent_version,
                            **error_details(error),
                        )
                    )
    finally:
        writer.join(timeout=15)
        for direct in direct_clients:
            direct.close()

    expected_dependents = set(acknowledged_dependents)
    validation_deadline = time.monotonic() + 8.0
    observed_dependents: set[int] = set()
    while time.monotonic() < validation_deadline:
        final_document = wait_for_majority_version(validator, key, 0)
        observed_dependents = {
            item.get("sequence") for item in (final_document or {}).get("dependents", [])
        }
        if expected_dependents.issubset(observed_dependents):
            break
        time.sleep(0.05)
    missing_sequences = sorted(expected_dependents - observed_dependents)
    missing = len(missing_sequences)
    if missing:
        validation_id = new_operation_id("wfr-validation")
        now = time.monotonic_ns()
        recorder.write(
            operation_event(
                run_id=run_id,
                config=config,
                model=MODEL,
                seed=seed,
                iteration=iterations,
                operation_id=validation_id,
                operation="validate-dependent-writes",
                started_ns=now,
                ended_ns=now,
                status="ok",
                listener=listener,
                check=True,
                violation_count=missing,
                missing_sequences=missing_sequences,
            )
        )
        checks += 1
        violations += missing

    errors += len(writer_errors)
    return {"checks": checks, "violations": violations, "errors": errors}
