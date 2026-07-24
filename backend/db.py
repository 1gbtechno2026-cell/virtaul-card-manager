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

_client = None
_collection = None


def is_configured() -> bool:
    return bool(MONGODB_URI)


def get_collection():
    """Lazily connects on first use. Returns None if MONGODB_URI isn't set."""
    global _client, _collection

    if not is_configured():
        return None

    if _collection is None:
        from pymongo import MongoClient

        _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        _collection = _client[MONGODB_DB_NAME][COLLECTION_NAME]

    return _collection


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


def save_card(details: dict) -> None:
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
        }
    )


def get_all_cards(date_from: str | None = None, date_to: str | None = None, search: str | None = None) -> list:
    """Returns stored cards, most recent first, optionally filtered.

    date_from/date_to: 'YYYY-MM-DD' strings, inclusive on both ends.
    search: matched against card number or card alias (case-insensitive).

    Empty list if Mongo isn't configured."""
    collection = get_collection()
    if collection is None:
        return []

    query = {}

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
