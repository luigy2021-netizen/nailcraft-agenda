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


def upsert(
    salon_id: str,
    collection: str,
    doc_id: str | None,
    values: dict[str, Any],
) -> str:
    collection_ref = salon_ref(salon_id).collection(collection)

    if doc_id:
        ref = collection_ref.document(doc_id)
    else:
        ref = collection_ref.document()

    stored_values = {
        **values,
        "salon_id": salon_id,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }

    ref.set(stored_values, merge=True)
    return ref.id


def subscription_allows_booking(
    salon: dict[str, Any],
) -> bool:
    if salon.get("subscription_status") not in {
        "trial",
        "active",
    }:
        return False

    subscription_end = salon.get("subscription_end")

    if not subscription_end:
        return True

    timezone_name = salon.get(
        "timezone",
        "America/Ciudad_Juarez",
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

        subscription_end_date = subscription_end.astimezone(
            salon_timezone
        ).date()
    elif isinstance(subscription_end, date):
        subscription_end_date = subscription_end
    else:
        return False

    return subscription_end_date >= today


def local_datetime(
    day: date,
    value: time,
    timezone_name: str,
) -> datetime:
    return datetime.combine(
        day,
        value,
        ZoneInfo(timezone_name),
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


def schedule_breaks(hours: dict[str, Any]) -> list[tuple[time, time]]:
    configured_breaks = (
        hours.get("breaks")
        or hours.get("rests")
        or []
    )

    if isinstance(configured_breaks, dict):
        configured_breaks = [configured_breaks]

    breaks = []

    if isinstance(configured_breaks, list):
        for configured_break in configured_breaks:
            if not isinstance(configured_break, dict):
                continue

            break_start = parse_schedule_time(
                configured_break.get("start")
                or configured_break.get("break_start")
                or configured_break.get("rest_start")
            )
            break_end = parse_schedule_time(
                configured_break.get("end")
                or configured_break.get("break_end")
                or configured_break.get("rest_end")
            )

            if (
                break_start is not None
                and break_end is not None
                and break_end > break_start
            ):
                breaks.append((break_start, break_end))

    single_break_start = parse_schedule_time(
        hours.get("break_start")
        or hours.get("rest_start")
        or hours.get("lunch_start")
    )
    single_break_end = parse_schedule_time(
        hours.get("break_end")
        or hours.get("rest_end")
        or hours.get("lunch_end")
    )

    if (
        single_break_start is not None
        and single_break_end is not None
        and single_break_end > single_break_start
    ):
        breaks.append(
            (
                single_break_start,
                single_break_end,
            )
        )

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
    same_staff = appointment.get("staff_id") == staff_id
    same_desk = bool(
        desk_id
        and appointment.get("desk_id") == desk_id
    )

    return same_staff or same_desk


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
        appointment,
        staff_id,
        desk_id,
    ):
        return False

    appointment_start = appointment.get("start_at")
    appointment_end = appointment.get("end_at")

    if not isinstance(appointment_start, datetime):
        return False

    if not isinstance(appointment_end, datetime):
        return False

    return overlaps(
        slot_start,
        slot_end,
        appointment_start,
        appointment_end,
    )


def slot_overlaps_break(
    slot_start: datetime,
    slot_end: datetime,
    day: date,
    hours: dict[str, Any],
    timezone_name: str,
) -> bool:
    for break_start, break_end in schedule_breaks(hours):
        break_start_at = local_datetime(
            day,
            break_start,
            timezone_name,
        )
        break_end_at = local_datetime(
            day,
            break_end,
            timezone_name,
        )

        if overlaps(
            slot_start,
            slot_end,
            break_start_at,
            break_end_at,
        ):
            return True

    return False


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

    opening_time = parse_schedule_time(hours.get("start"))
    closing_time = parse_schedule_time(hours.get("end"))

    if (
        opening_time is None
        or closing_time is None
        or closing_time <= opening_time
    ):
        return []

    try:
        service_minutes = int(service["duration_minutes"])
    except (KeyError, TypeError, ValueError):
        return []

    if service_minutes <= 0 or step_minutes <= 0:
        return []

    opening = local_datetime(
        day,
        opening_time,
        timezone_name,
    )
    closing = local_datetime(
        day,
        closing_time,
        timezone_name,
    )
    duration = timedelta(minutes=service_minutes)

    existing = appointments_between(
        salon_id,
        opening,
        closing,
    )

    staff_id = staff.get("id", "")
    desk_id = staff.get("desk_id", "")
    current_time = datetime.now(ZoneInfo(timezone_name))

    starts = []
    cursor = opening

    while cursor + duration <= closing:
        slot_end = cursor + duration

        is_future = cursor > current_time
        is_break = slot_overlaps_break(
            cursor,
            slot_end,
            day,
            hours,
            timezone_name,
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
                "start_at",
                ">=",
                start,
            )
        )
        .where(
            filter=FieldFilter(
                "start_at",
                "<",
                end,
            )
        )
        .order_by("start_at")
    )

    return [
        {
            "id": document.id,
            **document.to_dict(),
        }
        for document in query.stream()
    ]


def create_booking_atomic(
    salon_id: str,
    salon: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[str, str]:
    """Reserva sin doble asignación.

    Devuelve el identificador de la cita y el código secreto
    utilizado para su autogestión.
    """
    database = db()
    appointments_ref = salon_ref(salon_id).collection(
        "appointments"
    )
    appointment_ref = appointments_ref.document()

    secret = secrets.token_urlsafe(12)
    secret_hash = hashlib.sha256(
        secret.encode()
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
        desk_id = payload.get("desk_id", "")

        if (
            not isinstance(start_at, datetime)
            or not isinstance(end_at, datetime)
            or end_at <= start_at
            or not staff_id
        ):
            raise ValueError("INVALID_BOOKING")

        query = appointments_ref.where(
            filter=FieldFilter(
                "start_at",
                "<",
                end_at,
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


def manage_booking(
    salon_id: str,
    appointment_id: str,
    secret: str,
    action: str,
    new_times: tuple[datetime, datetime] | None = None,
) -> None:
    appointment_ref = (
        salon_ref(salon_id)
        .collection("appointments")
        .document(appointment_id)
    )

    snapshot = appointment_ref.get()

    if not snapshot.exists:
        raise ValueError("NOT_FOUND")

    appointment = snapshot.to_dict()

    expected_secret = appointment.get(
        "manage_secret_hash",
        "",
    )
    supplied_secret = hashlib.sha256(
        secret.encode()
    ).hexdigest()

    if not secrets.compare_digest(
        expected_secret,
        supplied_secret,
    ):
        raise ValueError("INVALID_SECRET")

    if appointment.get("status") not in MANAGEABLE_APPOINTMENTS:
        raise ValueError("INVALID_STATUS")

    start_at = appointment.get("start_at")

    if not isinstance(start_at, datetime):
        raise ValueError("INVALID_BOOKING")

    if now_utc() > start_at - timedelta(hours=2):
        raise ValueError("TOO_LATE")

    if action == "cancel":
        appointment_ref.update(
            {
                "status": "cancelled_by_client",
                "cancelled_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
                "notification_status": "pending",
            }
        )
        return

    if action != "reschedule" or not new_times:
        raise ValueError("INVALID_ACTION")

    new_start, new_end = new_times

    if (
        not isinstance(new_start, datetime)
        or not isinstance(new_end, datetime)
        or new_end <= new_start
    ):
        raise ValueError("INVALID_BOOKING")

    database = db()
    appointments_ref = salon_ref(salon_id).collection(
        "appointments"
    )

    @firestore.transactional
    def transact(transaction):
        fresh_snapshot = appointment_ref.get(
            transaction=transaction
        )

        if not fresh_snapshot.exists:
            raise ValueError("NOT_FOUND")

        fresh_appointment = fresh_snapshot.to_dict()

        if (
            fresh_appointment.get("status")
            not in MANAGEABLE_APPOINTMENTS
        ):
            raise ValueError("INVALID_STATUS")

        fresh_start = fresh_appointment.get("start_at")

        if (
            not isinstance(fresh_start, datetime)
            or now_utc() > fresh_start - timedelta(hours=2)
        ):
            raise ValueError("TOO_LATE")

        staff_id = fresh_appointment.get("staff_id", "")
        desk_id = fresh_appointment.get("desk_id", "")

        query = appointments_ref.where(
            filter=FieldFilter(
                "start_at",
                "<",
                new_end,
            )
        )

        for other_snapshot in query.stream(
            transaction=transaction
        ):
            other_appointment = {
                "id": other_snapshot.id,
                **other_snapshot.to_dict(),
            }

            if appointment_blocks_slot(
                other_appointment,
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
