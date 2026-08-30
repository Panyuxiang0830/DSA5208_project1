from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from pymongo import MongoClient, ReadPreference, monitoring
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


MONGODB_URI = os.environ.get(
    "MONGODB_URI",
    "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0",
)
DATABASE_NAME = os.environ.get("EXPERIMENT_DATABASE", "dsa5208_baseline")


@dataclass(frozen=True)
class ExperimentConfig:
    config_id: str
    label: str
    causal_session: bool
    write_concern: str | int
    read_concern: str
    read_preference: str
    directed_secondary_reads: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


CONFIGS: dict[str, ExperimentConfig] = {
    "C1": ExperimentConfig(
        config_id="C1",
        label="causal-majority-primary",
        causal_session=True,
        write_concern="majority",
        read_concern="majority",
        read_preference="primary",
    ),
    "C2": ExperimentConfig(
        config_id="C2",
        label="causal-majority-secondary",
        causal_session=True,
        write_concern="majority",
        read_concern="majority",
        read_preference="secondary",
    ),
    "C3": ExperimentConfig(
        config_id="C3",
        label="noncausal-w1-local-directed-secondary",
        causal_session=False,
        write_concern=1,
        read_concern="local",
        read_preference="secondaryPreferred",
        directed_secondary_reads=True,
    ),
    "C4": ExperimentConfig(
        config_id="C4",
        label="noncausal-majority-primary",
        causal_session=False,
        write_concern="majority",
        read_concern="majority",
        read_preference="primary",
    ),
}


READ_PREFERENCES = {
    "primary": ReadPreference.PRIMARY,
    "secondary": ReadPreference.SECONDARY,
    "secondaryPreferred": ReadPreference.SECONDARY_PREFERRED,
}


class OperationServerListener(monitoring.CommandListener):
    """Associates a MongoDB command comment with the server that handled it."""

    def __init__(self) -> None:
        self._servers: dict[str, str] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _server_name(connection_id: Any) -> str:
        if isinstance(connection_id, tuple) and len(connection_id) >= 2:
            return f"{connection_id[0]}:{connection_id[1]}"
        return str(connection_id)

    def started(self, event: monitoring.CommandStartedEvent) -> None:
        comment = event.command.get("comment")
        if comment is None:
            return
        with self._lock:
            self._servers[str(comment)] = self._server_name(event.connection_id)

    def succeeded(self, event: monitoring.CommandSucceededEvent) -> None:
        return

    def failed(self, event: monitoring.CommandFailedEvent) -> None:
        return

    def pop(self, operation_id: str) -> str | None:
        with self._lock:
            return self._servers.pop(operation_id, None)


class JsonlRecorder:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._stream = path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def write(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._stream.write(json.dumps(event, sort_keys=True, default=str) + "\n")
            self._stream.flush()

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> JsonlRecorder:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def new_operation_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def make_client(
    listener: OperationServerListener,
    uri: str = MONGODB_URI,
    timeout_ms: int = 5000,
) -> MongoClient:
    return MongoClient(
        uri,
        appname="dsa5208-client-consistency",
        event_listeners=[listener],
        retryReads=False,
        retryWrites=False,
        serverSelectionTimeoutMS=timeout_ms,
        connectTimeoutMS=timeout_ms,
        localThresholdMS=1000,
    )


def configured_collection(
    client: MongoClient,
    config: ExperimentConfig,
    collection_name: str,
):
    database = client.get_database(
        DATABASE_NAME,
        read_preference=READ_PREFERENCES[config.read_preference],
        read_concern=ReadConcern(config.read_concern),
        write_concern=WriteConcern(config.write_concern, wtimeout=5000),
    )
    return database.get_collection(collection_name)


def validation_collection(client: MongoClient, collection_name: str):
    database = client.get_database(
        DATABASE_NAME,
        read_preference=ReadPreference.PRIMARY,
        read_concern=ReadConcern("majority"),
        write_concern=WriteConcern("majority", wtimeout=5000),
    )
    return database.get_collection(collection_name)


def direct_secondary_collections(
    client: MongoClient,
    listener: OperationServerListener,
    config: ExperimentConfig,
    collection_name: str,
) -> tuple[list[MongoClient], list[Any]]:
    hello = client.admin.command("hello")
    primary = hello.get("primary")
    candidate_hosts = sorted(host for host in hello.get("hosts", []) if host != primary)
    direct_clients: list[MongoClient] = []
    collections: list[Any] = []

    for host in candidate_hosts:
        direct = make_client(
            listener,
            f"mongodb://{host}/?directConnection=true",
            timeout_ms=1500,
        )
        try:
            direct_hello = direct.admin.command("hello")
        except Exception:
            direct.close()
            continue
        if not direct_hello.get("secondary"):
            direct.close()
            continue
        direct_clients.append(direct)
        database = direct.get_database(
            DATABASE_NAME,
            read_preference=ReadPreference.SECONDARY,
            read_concern=ReadConcern(config.read_concern),
            write_concern=WriteConcern(config.write_concern, wtimeout=5000),
        )
        collections.append(database.get_collection(collection_name))

    if not collections:
        for direct in direct_clients:
            direct.close()
        raise RuntimeError(
            f"Expected at least one reachable Secondary; candidates={candidate_hosts}"
        )

    return direct_clients, collections


@contextlib.contextmanager
def logical_session(
    client: MongoClient,
    config: ExperimentConfig,
) -> Iterator[Any | None]:
    if not config.causal_session:
        yield None
        return

    with client.start_session(causal_consistency=True) as session:
        yield session


def operation_event(
    *,
    run_id: str,
    config: ExperimentConfig,
    model: str,
    seed: int,
    iteration: int,
    operation_id: str,
    operation: str,
    started_ns: int,
    ended_ns: int,
    status: str,
    listener: OperationServerListener,
    check: bool = False,
    violation_count: int = 0,
    **details: Any,
) -> dict[str, Any]:
    return {
        "event_kind": "operation",
        "run_id": run_id,
        "scenario": os.environ.get("EXPERIMENT_SCENARIO", "S0-normal"),
        "config_id": config.config_id,
        "config": config.as_dict(),
        "model": model,
        "seed": seed,
        "iteration": iteration,
        "operation_id": operation_id,
        "operation": operation,
        "started_ns": started_ns,
        "ended_ns": ended_ns,
        "latency_ms": round((ended_ns - started_ns) / 1_000_000, 6),
        "status": status,
        "served_by": listener.pop(operation_id),
        "check": check,
        "violation_count": violation_count,
        **details,
    }


def error_details(error: Exception) -> dict[str, str]:
    return {
        "error_type": type(error).__name__,
        "error_message": str(error),
    }


def wait_for_majority_version(
    collection: Any,
    key: str,
    expected_version: int,
    timeout_seconds: float = 8.0,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_seconds
    last_document = None
    while time.monotonic() < deadline:
        last_document = collection.find_one({"_id": key})
        if last_document and last_document.get("version", -1) >= expected_version:
            return last_document
        time.sleep(0.05)
    return last_document
