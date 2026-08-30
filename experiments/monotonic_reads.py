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
)


MODEL = "monotonic-reads"


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
    collection_name = "monotonic_reads"
    collection = configured_collection(client, config, collection_name)
    validator = validation_collection(client, collection_name)
    key = f"{run_id}:{config.config_id}:{seed}"
    validator.replace_one({"_id": key}, {"_id": key, "version": 0}, upsert=True)

    direct_clients: list[Any] = []
    read_collections = [collection]
    if config.directed_secondary_reads:
        direct_clients, read_collections = direct_secondary_collections(
            client, listener, config, collection_name
        )

    writer_errors: list[Exception] = []
    writer_random = random.Random(seed ^ 0x5A5A)

    def background_writer() -> None:
        for version in range(1, iterations * 2 + 1):
            operation_id = new_operation_id("mr-background-write")
            started = time.monotonic_ns()
            try:
                collection.update_one(
                    {"_id": key},
                    {"$set": {"version": version, "writer_id": "mr-background"}},
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

    writer = threading.Thread(target=background_writer, name="mr-writer", daemon=True)
    writer.start()

    violations = 0
    errors = 0
    checks = 0
    last_seen = -1
    read_random = random.Random(seed)

    try:
        with logical_session(client, config) as session:
            for iteration in range(1, iterations + 1):
                operation_id = new_operation_id("mr-read")
                started = time.monotonic_ns()
                try:
                    read_collection = read_collections[(iteration - 1) % len(read_collections)]
                    document = read_collection.find_one(
                        {"_id": key}, session=session, comment=operation_id
                    )
                    ended = time.monotonic_ns()
                    observed = document.get("version", -1) if document else -1
                    violation = int(observed < last_seen)
                    violations += violation
                    checks += 1
                    recorder.write(
                        operation_event(
                            run_id=run_id,
                            config=config,
                            model=MODEL,
                            seed=seed,
                            iteration=iteration,
                            operation_id=operation_id,
                            operation="successive-read",
                            started_ns=started,
                            ended_ns=ended,
                            status="ok",
                            listener=listener,
                            check=True,
                            violation_count=violation,
                            previous_observed_version=last_seen,
                            observed_version=observed,
                        )
                    )
                    last_seen = max(last_seen, observed)
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
                            operation="successive-read",
                            started_ns=started,
                            ended_ns=ended,
                            status="error",
                            listener=listener,
                            check=True,
                            **error_details(error),
                        )
                    )
                time.sleep(read_random.uniform(0.0002, 0.0020))
    finally:
        writer.join(timeout=15)
        for direct in direct_clients:
            direct.close()

    errors += len(writer_errors)
    return {"checks": checks, "violations": violations, "errors": errors}
