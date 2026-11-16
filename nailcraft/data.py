from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .firebase import db

ACTIVE_APPOINTMENTS = {
    "booked",
    "confirmed",
    "completed",
}

MANAGEABLE_APPOINTMENTS = {
    "booked",
    "confirmed",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def salon_ref(salon_id: str):
    return db().collection("salons").document(salon_id)


def public_salon_by_slug(
    slug: str,
) -> tuple[str, dict[str, Any]] | None:
    query = (
        db()
        .collection("salons")
        .where(
            filter=FieldFilter(
                "slug",
                "==",
                slug.lower().strip(),
            )
        )
        .limit(1)
    )

    docs = list(query.stream())
    return (docs[0].id, docs[0].to_dict()) if docs else None


def salons_for_owner(
    email: str,
) -> list[tuple[str, dict[str, Any]]]:
    query = (
        db()
        .collection("salons")
        .where(
            filter=FieldFilter(
                "owner_emails",
                "array_contains",
                email.lower(),
            )
        )
    )

    return [
        (document.id, document.to_dict())
        for document in query.stream()
    ]


def all_salons() -> list[tuple[str, dict[str, Any]]]:
    return [
        (document.id, document.to_dict())
        for document in db().collection("salons").stream()
    ]


def list_docs(
    salon_id: str,
    collection: str,
) -> list[dict[str, Any]]:
    return [
        {
            "id": document.id,
            **document.to_dict(),
        }
        for document in (
            salon_ref(salon_id)
            .collection(collection)
            .stream()
        )
    ]
