from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .firebase import db

ACTIVE_APPOINTMENTS = {"booked", "confirmed", "completed"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def salon_ref(salon_id: str):
    return db().collection("salons").document(salon_id)


def public_salon_by_slug(slug: str) -> tuple[str, dict[str, Any]] | None:
    query = db().collection("salons").where(filter=FieldFilter("slug", "==", slug)).limit(1)
    docs = list(query.stream())
    return (docs[0].id, docs[0].to_dict()) if docs else None


def salons_for_owner(email: str) -> list[tuple[str, dict[str, Any]]]:
    q = db().collection("salons").where(filter=FieldFilter("owner_emails", "array_contains", email.lower()))
    return [(d.id, d.to_dict()) for d in q.stream()]


def all_salons() -> list[tuple[str, dict[str, Any]]]:
    return [(d.id, d.to_dict()) for d in db().collection("salons").stream()]


def list_docs(salon_id: str, collection: str) -> list[dict[str, Any]]:
    return [{"id": d.id, **d.to_dict()} for d in salon_ref(salon_id).collection(collection).stream()]


def upsert(salon_id: str, collection: str, doc_id: str | None, values: dict[str, Any]) -> str:
    ref = salon_ref(salon_id).collection(collection).document(doc_id) if doc_id else salon_ref(salon_id).collection(collection).document()
    values = {**values, "salon_id": salon_id, "updated_at": firestore.SERVER_TIMESTAMP}
    ref.set(values, merge=True)
    return ref.id


def subscription_allows_booking(salon: dict[str, Any]) -> bool:
    end = salon.get("subscription_end")
    if hasattr(end, "date"):
        end = end.date()
    return salon.get("subscription_status") in {"trial", "active"} and (not end or end >= date.today())


def local_datetime(day: date, value: time, timezone_name: str) -> datetime:
    return datetime.combine(day, value, ZoneInfo(timezone_name))


def available_starts(
    salon_id: str,
    staff: dict[str, Any],
    service: dict[str, Any],
    day: date,
    timezone_name: str,
    step_minutes: int = 15,
) -> list[datetime]:
    weekday = str(day.weekday())
    hours = (staff.get("schedule") or {}).get(weekday)
    if not hours or not staff.get("active", True):
        return []
    opening = local_datetime(day, time.fromisoformat(hours["start"]), timezone_name)
    closing = local_datetime(day, time.fromisoformat(hours["end"]), timezone_name)
    duration = timedelta(minutes=int(service["duration_minutes"]))
    existing = appointments_between(salon_id, opening, closing)
    starts, cursor = [], opening
    while cursor + duration <= closing:
        if cursor > datetime.now(ZoneInfo(timezone_name)) and all(
            a.get("staff_id") != staff["id"]
            or a.get("status") not in ACTIVE_APPOINTMENTS
            or cursor + duration <= a["start_at"]
            or cursor >= a["end_at"]
            for a in existing
        ):
            starts.append(cursor)
        cursor += timedelta(minutes=step_minutes)
    return starts


def appointments_between(salon_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    q = salon_ref(salon_id).collection("appointments").where(filter=FieldFilter("start_at", ">=", start)).where(filter=FieldFilter("start_at", "<", end)).order_by("start_at")
    return [{"id": d.id, **d.to_dict()} for d in q.stream()]


def create_booking_atomic(salon_id: str, salon: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str]:
    """Reserva sin doble asignación. Devuelve id y código secreto para autogestión."""
    database = db()
    appt_ref = salon_ref(salon_id).collection("appointments").document()
    secret = secrets.token_urlsafe(12)
    secret_hash = hashlib.sha256(secret.encode()).hexdigest()

    @firestore.transactional
    def transact(transaction):
        fresh = salon_ref(salon_id).get(transaction=transaction).to_dict() or {}
        if not subscription_allows_booking(fresh):
            raise ValueError("SUBSCRIPTION_EXPIRED")
        q = salon_ref(salon_id).collection("appointments").where(filter=FieldFilter("staff_id", "==", payload["staff_id"])).where(filter=FieldFilter("start_at", "<", payload["end_at"]))
        for snap in q.stream(transaction=transaction):
            item = snap.to_dict()
            if item.get("status") in ACTIVE_APPOINTMENTS and item.get("end_at") > payload["start_at"]:
                raise ValueError("SLOT_TAKEN")
        transaction.set(appt_ref, {**payload, "salon_id": salon_id, "status": "booked", "manage_secret_hash": secret_hash, "created_at": firestore.SERVER_TIMESTAMP, "updated_at": firestore.SERVER_TIMESTAMP})

    transact(database.transaction())
    return appt_ref.id, secret


def manage_booking(salon_id: str, appointment_id: str, secret: str, action: str, new_times: tuple[datetime, datetime] | None = None) -> None:
    ref = salon_ref(salon_id).collection("appointments").document(appointment_id)
    snap = ref.get()
    if not snap.exists:
        raise ValueError("NOT_FOUND")
    item = snap.to_dict()
    if not secrets.compare_digest(item.get("manage_secret_hash", ""), hashlib.sha256(secret.encode()).hexdigest()):
        raise ValueError("INVALID_SECRET")
    if now_utc() > item["start_at"] - timedelta(hours=2):
        raise ValueError("TOO_LATE")
    if action == "cancel":
        ref.update({"status": "cancelled_by_client", "cancelled_at": firestore.SERVER_TIMESTAMP, "updated_at": firestore.SERVER_TIMESTAMP, "notification_status": "pending"})
    elif action == "reschedule" and new_times:
        database = db()

        @firestore.transactional
        def transact(tx):
            query = salon_ref(salon_id).collection("appointments").where(filter=FieldFilter("staff_id", "==", item["staff_id"])).where(filter=FieldFilter("start_at", "<", new_times[1]))
            for other in query.stream(transaction=tx):
                value = other.to_dict()
                if other.id != appointment_id and value.get("status") in ACTIVE_APPOINTMENTS and value.get("end_at") > new_times[0]:
                    raise ValueError("SLOT_TAKEN")
            tx.update(ref, {"start_at": new_times[0], "end_at": new_times[1], "status": "booked", "rescheduled_at": firestore.SERVER_TIMESTAMP, "updated_at": firestore.SERVER_TIMESTAMP, "notification_status": "pending"})

        transact(database.transaction())


def gallery_change(salon_id: str, operation: str, image: dict[str, Any] | None = None, image_id: str | None = None) -> None:
    """Cuenta cada alta, reemplazo o baja como una operación mensual."""
    month = date.today().strftime("%Y-%m")
    counter = salon_ref(salon_id).collection("usage").document(month)
    transaction = db().transaction()

    @firestore.transactional
    def transact(tx):
        usage = counter.get(transaction=tx).to_dict() or {}
        if int(usage.get("gallery_changes", 0)) >= 3:
            raise ValueError("MONTHLY_LIMIT")
        gallery = salon_ref(salon_id).collection("gallery")
        if operation == "add":
            if len(list(gallery.stream(transaction=tx))) >= 10:
                raise ValueError("CAPACITY_LIMIT")
            ref = gallery.document()
            tx.set(ref, {**(image or {}), "salon_id": salon_id, "created_at": firestore.SERVER_TIMESTAMP})
        elif operation == "replace" and image_id:
            tx.set(gallery.document(image_id), {**(image or {}), "salon_id": salon_id, "updated_at": firestore.SERVER_TIMESTAMP}, merge=True)
        elif operation == "delete" and image_id:
            tx.delete(gallery.document(image_id))
        tx.set(counter, {"gallery_changes": firestore.Increment(1), "month": month}, merge=True)

    transact(transaction)


def seed_salon(name: str, slug: str, owner_email: str, timezone_name: str) -> str:
    if public_salon_by_slug(slug.lower().strip()):
        raise ValueError("SLUG_TAKEN")
    ref = db().collection("salons").document()
    ref.set({"name": name, "slug": slug.lower().strip(), "owner_emails": [owner_email.lower()], "owner_phone": "", "timezone": timezone_name, "subscription_status": "trial", "subscription_end": datetime.now(timezone.utc) + timedelta(days=15), "created_at": firestore.SERVER_TIMESTAMP, "updated_at": firestore.SERVER_TIMESTAMP})
    for number in range(1, 6):
        ref.collection("desks").document(str(number)).set({"number": number, "name": f"Escritorio {number}", "active": number == 1, "salon_id": ref.id})
    return ref.id
