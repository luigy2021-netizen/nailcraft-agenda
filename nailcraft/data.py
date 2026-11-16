
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
                "slug", "==", slug.lower().strip()
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
                email.lower().strip(),
            )
        )
    )
    return [
        (doc.id, doc.to_dict())
        for doc in query.stream()
    ]


def all_salons() -> list[tuple[str, dict[str, Any]]]:
    return [
        (doc.id, doc.to_dict())
        for doc in db().collection("salons").stream()
    ]


def list_docs(
    salon_id: str,
    collection: str,
) -> list[dict[str, Any]]:
    return [
        {"id": doc.id, **doc.to_dict()}
        for doc in (
            salon_ref(salon_id)
            .collection(collection)
            .stream()
        )
    ]


def upsert(
    salon_id: str,
    collection: str,
    doc_id: str | None,
    values: dict[str, Any],
) -> str:
    collection_ref = salon_ref(salon_id).collection(collection)
    ref = (
        collection_ref.document(doc_id)
        if doc_id
        else collection_ref.document()
    )
    ref.set(
        {
            **values,
            "salon_id": salon_id,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    return ref.id


def subscription_allows_booking(
    salon: dict[str, Any],
) -> bool:
    if salon.get("subscription_status") not in {
        "trial", "active"
    }:
        return False

    subscription_end = salon.get("subscription_end")
    if not subscription_end:
        return True

    timezone_name = salon.get(
        "timezone", "America/Ciudad_Juarez"
    )
    try:
        salon_timezone = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        salon_timezone = timezone.utc

    today = datetime.now(salon_timezone).date()

    if isinstance(subscription_end, datetime):
        if subscription_end.tzinfo is None:
            subscription_end = subscription_end.replace(
                tzinfo=timezone.utc
            )
        end_date = subscription_end.astimezone(
            salon_timezone
        ).date()
    elif isinstance(subscription_end, date):
        end_date = subscription_end
    else:
        return False

    return end_date >= today


def local_datetime(
    day: date,
    value: time,
    timezone_name: str,
) -> datetime:
    return datetime.combine(
        day, value, ZoneInfo(timezone_name)
    )


def parse_schedule_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    if not value:
        return None
    try:
        return time.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def schedule_breaks(
    hours: dict[str, Any],
) -> list[tuple[time, time]]:
    configured = (
        hours.get("breaks")
        or hours.get("rests")
        or []
    )
    if isinstance(configured, dict):
        configured = [configured]

    breaks = []

    if isinstance(configured, list):
        for item in configured:
            if not isinstance(item, dict):
                continue
            start = parse_schedule_time(
                item.get("start")
                or item.get("break_start")
                or item.get("rest_start")
            )
            end = parse_schedule_time(
                item.get("end")
                or item.get("break_end")
                or item.get("rest_end")
            )
            if start and end and end > start:
                breaks.append((start, end))

    start = parse_schedule_time(
        hours.get("break_start")
        or hours.get("rest_start")
        or hours.get("lunch_start")
    )
    end = parse_schedule_time(
        hours.get("break_end")
        or hours.get("rest_end")
        or hours.get("lunch_end")
    )
    if start and end and end > start:
        breaks.append((start, end))

    return breaks


def overlaps(
    start_a: datetime,
    end_a: datetime,
    start_b: datetime,
    end_b: datetime,
) -> bool:
    return start_a < end_b and end_a > start_b


def appointment_uses_resource(
    appointment: dict[str, Any],
    staff_id: str,
    desk_id: str,
) -> bool:
    return (
        appointment.get("staff_id") == staff_id
        or bool(
            desk_id
            and appointment.get("desk_id") == desk_id
        )
    )


def appointment_blocks_slot(
    appointment: dict[str, Any],
    staff_id: str,
    desk_id: str,
    slot_start: datetime,
    slot_end: datetime,
    ignored_appointment_id: str | None = None,
) -> bool:
    if (
        ignored_appointment_id
        and appointment.get("id") == ignored_appointment_id
    ):
        return False

    if appointment.get("status") not in ACTIVE_APPOINTMENTS:
        return False

    if not appointment_uses_resource(
        appointment, staff_id, desk_id
    ):
        return False

    start = appointment.get("start_at")
    end = appointment.get("end_at")

    if not isinstance(start, datetime):
        return False
    if not isinstance(end, datetime):
        return False

    return overlaps(
        slot_start, slot_end, start, end
    )


def slot_overlaps_break(
    slot_start: datetime,
    slot_end: datetime,
    day: date,
    hours: dict[str, Any],
    timezone_name: str,
) -> bool:
    for break_start, break_end in schedule_breaks(hours):
        start = local_datetime(
            day, break_start, timezone_name
        )
        end = local_datetime(
            day, break_end, timezone_name
        )
        if overlaps(slot_start, slot_end, start, end):
            return True
    return False


def appointments_between(
    salon_id: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    query = (
        salon_ref(salon_id)
        .collection("appointments")
        .where(
            filter=FieldFilter(
                "start_at", ">=", start
            )
        )
        .where(
            filter=FieldFilter(
                "start_at", "<", end
            )
        )
        .order_by("start_at")
    )
    return [
        {"id": doc.id, **doc.to_dict()}
        for doc in query.stream()
    ]


def validate_slot(
    salon_id: str,
    staff_id: str,
    service_id: str,
    desk_id: str,
    start_at: datetime,
    end_at: datetime,
    transaction=None,
) -> tuple[dict, dict]:
    """Valida personal, servicio, escritorio y horario."""

    if (
        not isinstance(start_at, datetime)
        or not isinstance(end_at, datetime)
        or start_at.tzinfo is None
        or end_at.tzinfo is None
        or end_at <= start_at
        or not staff_id
        or not service_id
    ):
        raise ValueError("INVALID_BOOKING")

    salon_snapshot = salon_ref(salon_id).get(
        transaction=transaction
    )
    if not salon_snapshot.exists:
        raise ValueError("SALON_NOT_FOUND")

    salon = salon_snapshot.to_dict()
    timezone_name = salon.get(
        "timezone", "America/Ciudad_Juarez"
    )

    try:
        salon_timezone = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        raise ValueError("INVALID_TIMEZONE") from None

    local_start = start_at.astimezone(salon_timezone)
    local_end = end_at.astimezone(salon_timezone)

    if start_at <= now_utc():
        raise ValueError("PAST_SLOT")

    if local_start.date() != local_end.date():
        raise ValueError("OUTSIDE_SCHEDULE")

    if local_start.date() > (
        datetime.now(salon_timezone).date()
        + timedelta(days=90)
    ):
        raise ValueError("OUTSIDE_BOOKING_WINDOW")

    staff_ref = (
        salon_ref(salon_id)
        .collection("staff")
        .document(staff_id)
    )
    staff_snapshot = staff_ref.get(transaction=transaction)
    if not staff_snapshot.exists:
        raise ValueError("STAFF_NOT_FOUND")

    staff = staff_snapshot.to_dict()
    if not staff.get("active", True):
        raise ValueError("STAFF_INACTIVE")

    service_ref = (
        salon_ref(salon_id)
        .collection("services")
        .document(service_id)
    )
    service_snapshot = service_ref.get(
        transaction=transaction
    )
    if not service_snapshot.exists:
        raise ValueError("SERVICE_NOT_FOUND")

    service = service_snapshot.to_dict()
    if not service.get("active", True):
        raise ValueError("SERVICE_INACTIVE")

    if service_id not in staff.get("service_ids", []):
        raise ValueError("SERVICE_NOT_ASSIGNED")

    assigned_desk = staff.get("desk_id", "")
    if not assigned_desk or assigned_desk != desk_id:
        raise ValueError("INVALID_DESK")

    desk_ref = (
        salon_ref(salon_id)
        .collection("desks")
        .document(desk_id)
    )
    desk_snapshot = desk_ref.get(transaction=transaction)
    if not desk_snapshot.exists:
        raise ValueError("DESK_NOT_FOUND")
    if not desk_snapshot.to_dict().get("active", False):
        raise ValueError("DESK_INACTIVE")

    try:
        duration = int(service["duration_minutes"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("INVALID_SERVICE") from None

    if (
        duration <= 0
        or end_at - start_at != timedelta(minutes=duration)
    ):
        raise ValueError("INVALID_DURATION")

    weekday = str(local_start.weekday())
    hours = (staff.get("schedule") or {}).get(weekday)

    if not isinstance(hours, dict):
        raise ValueError("OUTSIDE_SCHEDULE")

    opening = parse_schedule_time(hours.get("start"))
    closing = parse_schedule_time(hours.get("end"))

    if not opening or not closing or closing <= opening:
        raise ValueError("OUTSIDE_SCHEDULE")

    opening_at = local_datetime(
        local_start.date(), opening, timezone_name
    )
    closing_at = local_datetime(
        local_start.date(), closing, timezone_name
    )

    if start_at < opening_at or end_at > closing_at:
        raise ValueError("OUTSIDE_SCHEDULE")

    if slot_overlaps_break(
        start_at,
        end_at,
        local_start.date(),
        hours,
        timezone_name,
    ):
        raise ValueError("BREAK_CONFLICT")

    return staff, service


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

    if not service.get("active", True):
        return []

    opening_time = parse_schedule_time(
        hours.get("start")
    )
    closing_time = parse_schedule_time(
        hours.get("end")
    )

    if (
        opening_time is None
        or closing_time is None
        or closing_time <= opening_time
    ):
        return []

    try:
        duration_minutes = int(
            service["duration_minutes"]
        )
    except (KeyError, TypeError, ValueError):
        return []

    if duration_minutes <= 0 or step_minutes <= 0:
        return []

    desk_id = staff.get("desk_id", "")
    if not desk_id:
        return []

    desk_snapshot = (
        salon_ref(salon_id)
        .collection("desks")
        .document(desk_id)
        .get()
    )
    if (
        not desk_snapshot.exists
        or not desk_snapshot.to_dict().get("active", False)
    ):
        return []

    opening = local_datetime(
        day, opening_time, timezone_name
    )
    closing = local_datetime(
        day, closing_time, timezone_name
    )
    duration = timedelta(minutes=duration_minutes)

    existing = appointments_between(
        salon_id, opening, closing
    )

    staff_id = staff.get("id", "")
    current_time = datetime.now(ZoneInfo(timezone_name))
    starts = []
    cursor = opening

    while cursor + duration <= closing:
        slot_end = cursor + duration

        is_future = cursor > current_time
        is_break = slot_overlaps_break(
            cursor, slot_end, day, hours, timezone_name
        )
        is_occupied = any(
            appointment_blocks_slot(
                appointment,
                staff_id,
                desk_id,
                cursor,
                slot_end,
            )
            for appointment in existing
        )

        if is_future and not is_break and not is_occupied:
            starts.append(cursor)

        cursor += timedelta(minutes=step_minutes)

    return starts


def create_booking_atomic(
    salon_id: str,
    salon: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[str, str]:
    """Crea una reservación con control transaccional."""

    database = db()
    appointments_ref = (
        salon_ref(salon_id).collection("appointments")
    )
    appointment_ref = appointments_ref.document()

    secret = secrets.token_urlsafe(24)
    secret_hash = hashlib.sha256(
        secret.encode("utf-8")
    ).hexdigest()

    @firestore.transactional
    def transact(transaction):
        fresh_snapshot = salon_ref(salon_id).get(
            transaction=transaction
        )
        fresh_salon = (
            fresh_snapshot.to_dict()
            if fresh_snapshot.exists
            else {}
        )

        if not subscription_allows_booking(fresh_salon):
            raise ValueError("SUBSCRIPTION_EXPIRED")

        start_at = payload.get("start_at")
        end_at = payload.get("end_at")
        staff_id = payload.get("staff_id", "")
        service_id = payload.get("service_id", "")
        desk_id = payload.get("desk_id", "")

        validate_slot(
            salon_id,
            staff_id,
            service_id,
            desk_id,
            start_at,
            end_at,
            transaction=transaction,
        )

        query = appointments_ref.where(
            filter=FieldFilter(
                "start_at", "<", end_at
            )
        )

        for snapshot in query.stream(
            transaction=transaction
        ):
            appointment = {
                "id": snapshot.id,
                **snapshot.to_dict(),
            }
            if appointment_blocks_slot(
                appointment,
                staff_id,
                desk_id,
                start_at,
                end_at,
            ):
                raise ValueError("SLOT_TAKEN")

        transaction.set(
            appointment_ref,
            {
                **payload,
                "salon_id": salon_id,
                "status": "booked",
                "manage_secret_hash": secret_hash,
                "created_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
        )

    transact(database.transaction())
    return appointment_ref.id, secret


def validate_manage_token(
    salon_id: str,
    appointment_id: str,
    secret: str,
) -> dict[str, Any]:
    """Valida el enlace antes de revelar datos de la cita."""

    if not appointment_id or not secret:
        raise ValueError("INVALID_SECRET")

    snapshot = (
        salon_ref(salon_id)
        .collection("appointments")
        .document(appointment_id)
        .get()
    )

    if not snapshot.exists:
        raise ValueError("NOT_FOUND")

    appointment = snapshot.to_dict()
    expected_hash = appointment.get(
        "manage_secret_hash", ""
    )

    supplied_hash = hashlib.sha256(
        secret.encode("utf-8")
    ).hexdigest()

    if not (
        isinstance(expected_hash, str)
        and secrets.compare_digest(
            expected_hash, supplied_hash
        )
    ):
        raise ValueError("INVALID_SECRET")

    return {
        "id": snapshot.id,
        **appointment,
    }


def manage_booking(
    salon_id: str,
    appointment_id: str,
    secret: str,
    action: str,
    new_times: tuple[datetime, datetime] | None = None,
) -> None:
    """Cancela o reprograma una cita autorizada."""

    if action not in {"cancel", "reschedule"}:
        raise ValueError("INVALID_ACTION")

    database = db()
    appointments_ref = (
        salon_ref(salon_id).collection("appointments")
    )
    appointment_ref = appointments_ref.document(
        appointment_id
    )

    @firestore.transactional
    def transact(transaction):
        snapshot = appointment_ref.get(
            transaction=transaction
        )
        if not snapshot.exists:
            raise ValueError("NOT_FOUND")

        appointment = snapshot.to_dict()
        expected_hash = appointment.get(
            "manage_secret_hash", ""
        )
        supplied_hash = hashlib.sha256(
            secret.encode("utf-8")
        ).hexdigest()

        if not (
            isinstance(expected_hash, str)
            and secrets.compare_digest(
                expected_hash, supplied_hash
            )
        ):
            raise ValueError("INVALID_SECRET")

        if appointment.get("status") not in MANAGEABLE_APPOINTMENTS:
            raise ValueError("INVALID_STATUS")

        original_start = appointment.get("start_at")
        if not isinstance(original_start, datetime):
            raise ValueError("INVALID_BOOKING")

        if now_utc() > original_start - timedelta(hours=2):
            raise ValueError("TOO_LATE")

        if action == "cancel":
            transaction.update(
                appointment_ref,
                {
                    "status": "cancelled_by_client",
                    "cancelled_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                    "notification_status": "pending",
                },
            )
            return

        if not new_times:
            raise ValueError("INVALID_BOOKING")

        new_start, new_end = new_times
        staff_id = appointment.get("staff_id", "")
        service_id = appointment.get("service_id", "")
        desk_id = appointment.get("desk_id", "")

        validate_slot(
            salon_id,
            staff_id,
            service_id,
            desk_id,
            new_start,
            new_end,
            transaction=transaction,
        )

        query = appointments_ref.where(
            filter=FieldFilter(
                "start_at", "<", new_end
            )
        )

        for other_snapshot in query.stream(
            transaction=transaction
        ):
            other = {
                "id": other_snapshot.id,
                **other_snapshot.to_dict(),
            }
            if appointment_blocks_slot(
                other,
                staff_id,
                desk_id,
                new_start,
                new_end,
                ignored_appointment_id=appointment_id,
            ):
                raise ValueError("SLOT_TAKEN")

        transaction.update(
            appointment_ref,
            {
                "start_at": new_start,
                "end_at": new_end,
                "status": "booked",
                "rescheduled_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
                "notification_status": "pending",
            },
        )

    transact(database.transaction())


def get_collage(
    salon_id: str,
) -> dict[str, Any] | None:
    snapshot = (
        salon_ref(salon_id)
        .collection("presentation")
        .document("collage")
        .get()
    )
    return snapshot.to_dict() if snapshot.exists else None


def save_collage(
    salon_id: str,
    image: dict[str, Any],
) -> None:
    (
        salon_ref(salon_id)
        .collection("presentation")
        .document("collage")
        .set(
            {
                **image,
                "salon_id": salon_id,
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
    )


def remove_collage(salon_id: str) -> None:
    (
        salon_ref(salon_id)
        .collection("presentation")
        .document("collage")
        .delete()
    )


def seed_salon(
    name: str,
    slug: str,
    owner_email: str,
    timezone_name: str,
) -> str:
    normalized_slug = slug.lower().strip()
    normalized_email = owner_email.lower().strip()

    if public_salon_by_slug(normalized_slug):
        raise ValueError("SLUG_TAKEN")

    try:
        salon_timezone = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        raise ValueError("INVALID_TIMEZONE") from None

    local_now = datetime.now(salon_timezone)
    subscription_end = (
        local_now + timedelta(days=15)
    ).astimezone(timezone.utc)

    ref = db().collection("salons").document()

    ref.set(
        {
            "name": name.strip(),
            "slug": normalized_slug,
            "owner_emails": [normalized_email],
            "owner_phone": "",
            "timezone": timezone_name,
            "subscription_status": "trial",
            "subscription_end": subscription_end,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
    )

    for number in range(1, 6):
        (
            ref.collection("desks")
            .document(str(number))
            .set(
                {
                    "number": number,
                    "name": f"Escritorio {number}",
                    "active": number == 1,
                    "salon_id": ref.id,
                }
            )
        )

    return ref.id
