"""Operator commands, run on the server with database access.

    python -m app.cli make-admin someone@example.com
    python -m app.cli revoke-admin someone@example.com
    python -m app.cli disable someone@example.com
    python -m app.cli enable someone@example.com
    python -m app.cli seed-suppliers        # add the starter supplier listings (safe to rerun)
"""
import argparse
import os
import sys
import uuid
from datetime import datetime, timezone

from pymongo import MongoClient

from .config import Settings

COMMANDS = {
    "make-admin": {"$set": {"role": "admin"}},
    "revoke-admin": {"$set": {"role": "contractor"}},
    # Disabling also signs the account out everywhere.
    "disable": {"$set": {"disabled": True}, "$inc": {"token_version": 1}},
    "enable": {"$set": {"disabled": False}},
}


def run(db, command: str, email: str) -> tuple[bool, str]:
    user = db.users.find_one({"email": email.lower()}, {"_id": 1})
    if user is None:
        return False, f"No account with email {email}"
    db.users.update_one({"_id": user["_id"]}, COMMANDS[command])
    db.audit_log.insert_one(
        {
            "_id": uuid.uuid4().hex,
            "user_id": None,
            "timestamp": datetime.now(timezone.utc),
            "action": f"CLI {command}",
            "record_id": user["_id"],
            "status": 200,
        }
    )
    return True, f"{command}: done for {email}"


def seed_suppliers(url: str, name: str) -> int:
    import asyncio

    from motor.motor_asyncio import AsyncIOMotorClient

    from .suppliers import seed

    added = asyncio.run(seed(AsyncIOMotorClient(url)[name]))
    print(f"seed-suppliers: {added} added")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    url = os.environ.get("TC_MONGO_URL", Settings.mongo_url)
    name = os.environ.get("TC_DB_NAME", Settings.db_name)
    if argv[:1] == ["seed-suppliers"]:
        return seed_suppliers(url, name)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("email")
    args = parser.parse_args(argv)
    with MongoClient(url) as client:
        ok, message = run(client[name], args.command, args.email)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
