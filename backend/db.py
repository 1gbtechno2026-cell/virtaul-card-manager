"""
MongoDB storage for created card records -- the sole place card data is
saved, lets you query and download card history at any point.

If MONGODB_URI isn't set in .env, storage functions no-op (return empty/
do nothing) rather than raising -- but app.py's /create endpoint checks
is_connected() first and refuses to create cards without a working
database, so this only matters for read-only endpoints during setup.
"""

from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent / ".env")

MONGODB_URI = os.environ.get("MONGODB_URI", "").strip()
MONGODB_DB_NAME = os.environ.get("MONGODB_DB_NAME", "virtual_card_creator").strip()
COLLECTION_NAME = "cards"
BATCHES_COLLECTION_NAME = "batches"

_client = None
_collection = None
_batches_collection = None


def is_configured() -> bool:
    return bool(MONGODB_URI)


def get_collection():
    """Lazily connects on first use. Returns None if MONGODB_URI isn't set."""
    global _client, _collection

    if not is_configured():
        return None

    if _collection is None:
        from pymongo import MongoClient

        if _client is None:
            _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        _collection = _client[MONGODB_DB_NAME][COLLECTION_NAME]

    return _collection


def get_batches_collection():
    """Lazily connects on first use. Returns None if MONGODB_URI isn't set."""
    global _client, _batches_collection

    if not is_configured():
        return None

    if _batches_collection is None:
        from pymongo import MongoClient

        if _client is None:
            _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        _batches_collection = _client[MONGODB_DB_NAME][BATCHES_COLLECTION_NAME]

    return _batches_collection


def is_connected() -> bool:
    """Actually pings MongoDB to confirm it's reachable right now -- unlike
    is_configured(), which only checks that a URI string was provided."""
    collection = get_collection()
    if collection is None:
        return False
    try:
        collection.database.client.admin.command("ping")
        return True
    except Exception:
        return False


def save_card(details: dict, batch_id: str | None = None) -> None:
    """Inserts one card record. No-op if Mongo isn't configured. Raises
    on a real connection/write failure so the caller can log it -- but
    should not be allowed to break card creation itself."""
    collection = get_collection()
    if collection is None:
        return

    collection.insert_one(
        {
            "card_alias": details.get("card_alias", ""),
            "card_number": details.get("card_number", ""),
            "card_amount": details.get("card_amount", ""),
            "expiry": details.get("expiry", ""),
            "cvc": details.get("cvc", ""),
            "billing_name": details.get("billing_name", ""),
            "description": details.get("description", ""),
            "created_by": details.get("created_by", ""),
            "created_at": datetime.now(timezone.utc),
            "batch_id": batch_id,
        }
    )


def create_batch(description: str, created_by: str, requested_count: int) -> str:
    """Inserts a 'running' batch record for one Create Cards run. Returns
    its id (used as batch_id on every card the run creates), or "" if
    Mongo isn't configured -- callers that reach this point have already
    confirmed a working connection via is_connected(), so this is just a
    defensive fallback, not the normal path."""
    collection = get_batches_collection()
    if collection is None:
        return ""

    result = collection.insert_one(
        {
            "description": description,
            "created_by": created_by,
            "requested_count": requested_count,
            "created_count": 0,
            "status": "running",
            "started_at": datetime.now(timezone.utc),
            "finished_at": None,
            "error": None,
        }
    )
    return str(result.inserted_id)


def finish_batch(batch_id: str, status: str, error: str | None = None) -> None:
    """Finalizes a batch record. created_count is computed by counting
    actual `cards` documents for this batch_id rather than trusting a
    passed-in number -- a batch that fails partway through still has its
    already-created cards saved, so the DB is the only reliable source
    for how many actually got made."""
    if not batch_id:
        return

    batches = get_batches_collection()
    cards = get_collection()
    if batches is None or cards is None:
        return

    from bson import ObjectId

    created_count = cards.count_documents({"batch_id": batch_id})
    batches.update_one(
        {"_id": ObjectId(batch_id)},
        {
            "$set": {
                "status": status,
                "error": error,
                "created_count": created_count,
                "finished_at": datetime.now(timezone.utc),
            }
        },
    )


def get_all_batches() -> list:
    """Returns stored batches, most recent first. Empty list if Mongo
    isn't configured."""
    collection = get_batches_collection()
    if collection is None:
        return []

    docs = list(collection.find().sort("started_at", -1))
    for doc in docs:
        doc["batch_id"] = str(doc.pop("_id"))
        for field in ("started_at", "finished_at"):
            value = doc.get(field)
            if isinstance(value, datetime) and value.tzinfo is None:
                doc[field] = value.replace(tzinfo=timezone.utc).isoformat()
            elif isinstance(value, datetime):
                doc[field] = value.isoformat()
    return docs


def get_all_cards(
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    batch_id: str | None = None,
) -> list:
    """Returns stored cards, most recent first, optionally filtered.

    date_from/date_to: 'YYYY-MM-DD' strings, inclusive on both ends.
    search: matched against card number or card alias (case-insensitive).
    batch_id: restricts to cards created by one Create Cards run.

    Empty list if Mongo isn't configured."""
    collection = get_collection()
    if collection is None:
        return []

    query = {}
    if batch_id:
        query["batch_id"] = batch_id

    date_filter = {}
    if date_from:
        try:
            date_filter["$gte"] = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if date_to:
        try:
            end = datetime.fromisoformat(date_to).replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            date_filter["$lte"] = end
        except ValueError:
            pass
    if date_filter:
        query["created_at"] = date_filter

    if search:
        regex = {"$regex": search, "$options": "i"}
        query["$or"] = [{"card_number": regex}, {"card_alias": regex}]

    docs = list(collection.find(query).sort("created_at", -1))
    for doc in docs:
        doc["_id"] = str(doc["_id"])
        created_at = doc.get("created_at")
        if isinstance(created_at, datetime):
            # pymongo returns naive datetimes by default, but everything
            # we store is UTC (see save_card) -- reattach that tzinfo so
            # the isoformat string carries an explicit UTC offset. Without
            # it, the frontend's `new Date(...)` would misread this as
            # local time instead of UTC, shifting the displayed time by
            # your timezone offset.
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            doc["created_at"] = created_at.isoformat()
    return docs
