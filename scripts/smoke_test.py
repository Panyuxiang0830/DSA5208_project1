import json
import os
import sys
import time
import uuid

from pymongo import MongoClient, ReadPreference
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


MONGODB_URI = os.environ.get(
    "MONGODB_URI",
    "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0",
)


def connect_with_retry(timeout_seconds: int = 60) -> MongoClient:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=3000,
            connectTimeoutMS=3000,
            retryWrites=True,
        )
        try:
            client.admin.command("ping")
            return client
        except PyMongoError as error:
            last_error = error
            client.close()
            time.sleep(1)

    raise RuntimeError(f"MongoDB was not ready within {timeout_seconds}s: {last_error}")


def main() -> int:
    client = connect_with_retry()
    hello = client.admin.command("hello")

    collection = client.get_database(
        "dsa5208",
        read_concern=ReadConcern("majority"),
        write_concern=WriteConcern("majority", wtimeout=5000),
        read_preference=ReadPreference.PRIMARY,
    ).get_collection("deployment_smoke_test")

    operation_id = str(uuid.uuid4())
    document = {
        "_id": operation_id,
        "value": "replica-set-ready",
        "version": 1,
    }

    with client.start_session(causal_consistency=True) as session:
        collection.insert_one(document, session=session)
        observed = collection.find_one({"_id": operation_id}, session=session)

    result = {
        "ok": observed == document,
        "primary": hello.get("primary"),
        "hosts": sorted(hello.get("hosts", [])),
        "operation_id": operation_id,
        "observed": observed,
    }
    print(json.dumps(result, indent=2, default=str))

    client.close()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # smoke test should print one actionable failure
        print(f"Smoke test failed: {error}", file=sys.stderr)
        raise

