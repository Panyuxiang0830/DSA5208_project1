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
    # C5-C8: controlled 2x2 read/write-concern matrix, causal session and
    # secondary read preference held fixed (except C8, which flips causal
    # off to isolate the session's own contribution). Compare against C2,
    # which is the majority/majority corner of the same matrix.
    "C5": ExperimentConfig(
        config_id="C5",
        label="causal-w1-majority-secondary",
        causal_session=True,
        write_concern=1,
        read_concern="majority",
        read_preference="secondary",
    ),
    "C6": ExperimentConfig(
        config_id="C6",
        label="causal-majority-local-secondary",
        causal_session=True,
        write_concern="majority",
        read_concern="local",
        read_preference="secondary",
    ),
    "C7": ExperimentConfig(
        config_id="C7",
        label="causal-w1-local-secondary",
        causal_session=True,
        write_concern=1,
        read_concern="local",
        read_preference="secondary",
    ),
    "C8": ExperimentConfig(
        config_id="C8",
        label="noncausal-majority-majority-secondary",
        causal_session=False,
        write_concern="majority",
        read_concern="majority",
        read_preference="secondary",
    ),
}

# C1-C4: the original representative-configuration experiment matrix.
CORE_CONFIGS: tuple[str, ...] = ("C1", "C2", "C3", "C4")
# C5-C8: controlled concern-matrix / causal-session-ablation extension.
# See CONFIGS above and report/generate_reports.py for the 2x2 matrix
# (C2, C5, C6, C7) and the session ablation pair (C2, C8).
EXTENDED_CONFIGS: tuple[str, ...] = ("C5", "C6", "C7", "C8")
ALL_CONFIGS: tuple[str, ...] = CORE_CONFIGS + EXTENDED_CONFIGS


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


TARGET_SECONDARY_ENV = "EXPERIMENT_TARGET_SECONDARY"


def direct_secondary_collections(
    client: MongoClient,
    listener: OperationServerListener,
    config: ExperimentConfig,
    collection_name: str,
) -> tuple[list[MongoClient], list[Any]]:
    """Open direct connections to every reachable Secondary, for callers that
    alternate reads across all of them (C3, and C8 under S4)."""
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


def resolve_read_collections(
    client: MongoClient,
    listener: OperationServerListener,
    config: ExperimentConfig,
    collection_name: str,
    default_collection: Any,
) -> tuple[list[MongoClient], list[Any]]:
    """Decide which collection object(s) a model's reads should cycle through.

    - read_preference == "primary" (C1, C4): always the normally configured,
      Primary-routed collection; Secondary targeting is meaningless here.
    - config.directed_secondary_reads (C3), or any other non-causal config
      (currently C8 only) once EXPERIMENT_TARGET_SECONDARY is set (S4
      controlled-matrix runs): direct connections to every reachable
      Secondary, alternated by the caller. This deliberately does NOT narrow
      to just the paused member -- with only two Secondaries in this
      deployment, alternating over both already guarantees every config
      exercises the same lagging node on the same schedule, and pinning
      exclusively to it produces a degenerate result for monotonic-reads (a
      read that always lands on a node which never even replicates this
      run's freshly created document returns "not found" every time, which
      trivially satisfies "never went backward"). C3's already-published
      results use this same unfiltered alternation, so C8 now matches it
      exactly instead of introducing a second, inconsistent mechanism.
    - causal-session configs (C2, C5, C6, C7) are NEVER routed through a
      direct connection: PyMongo forbids using a session with any
      MongoClient other than the one that created it, so a session-bound
      read cannot be pinned to an ad hoc direct client. These configs always
      go through the normally configured, driver-routed collection instead,
      which lets the driver's own server selection sometimes land on the
      paused Secondary -- and for a causal session that is the scenario we
      actually want to observe (afterClusterTime makes the server wait
      rather than return a stale value; see read_max_time_ms()).
    """
    if config.read_preference == "primary":
        return [], [default_collection]
    if config.directed_secondary_reads:
        return direct_secondary_collections(client, listener, config, collection_name)
    if os.environ.get(TARGET_SECONDARY_ENV) and not config.causal_session:
        return direct_secondary_collections(client, listener, config, collection_name)
    return [], [default_collection]


def read_max_time_ms(config: ExperimentConfig) -> int | None:
    """Server-side time limit (ms) for a model's per-iteration reads.

    Only causal-session configs need this, and only during S4: a causal read
    (afterClusterTime) that lands on the Secondary whose oplog application is
    paused will not return a stale value -- it blocks on the server until
    that node catches up, which under S4 never happens before the failpoint
    is disabled at scenario cleanup. Without a bound, one unlucky server
    selection would hang the whole run instead of surfacing as an operation
    error. Non-causal configs (C1, C3, C4, C8) never wait on afterClusterTime
    and do not need this. 300ms is deliberately short: the interesting signal
    is *whether* the operation errors out instead of returning a stale value,
    not how long it waits before doing so, and a short bound keeps a 500x3
    formal run tractable (a healthy Secondary that already satisfies
    afterClusterTime answers in low single-digit milliseconds either way).
    """
    if not config.causal_session:
        return None
    if not os.environ.get(TARGET_SECONDARY_ENV):
        return None
    return 300


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
