from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import streamlit as st
from firebase_admin import firestore

from nailcraft.data import (
    all_salons,
    appointments_between,
    available_starts,
    create_booking_atomic,
    get_collage,
    list_docs,
    manage_booking,
    public_salon_by_slug,
    remove_collage,
    salon_ref,
    salons_for_owner,
    seed_salon,
    save_collage,
    subscription_allows_booking,
    validate_manage_token,
    upsert,
)
from nailcraft.media import delete_image, upload_image

st.set_page_config(page_title="Nail Craft", page_icon="💅", layout="wide")

STATUS_LABEL = {
    "booked": "Reservada",
    "confirmed": "Confirmada",
    "completed": "Completada",
    "cancelled_by_client": "Cancelada por clienta",
    "cancelled_by_salon": "Cancelada por salón",
    "no_show": "No asistió",
}

DAYS = [
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
]


def qp(name: str, default: str = "") -> str:
    value = st.query_params.get(name, default)
    return value[0] if isinstance(value, list) else value


def money(value) -> str:
    return f"${float(value or 0):,.2f}"


def staff_map(salon_id: str):
    return {x["id"]: x for x in list_docs(salon_id, "staff")}


def service_map(salon_id: str):
    return {x["id"]: x for x in list_docs(salon_id, "services")}


def time_to_minutes(value) -> int | None:
    if isinstance(value, time):
        return value.hour * 60 + value.minute

    if not value:
        return None

    try:
        parsed = time.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None

    return parsed.hour * 60 + parsed.minute


def schedule_breaks(day_schedule: dict) -> list[dict]:
    breaks = day_schedule.get("breaks") or day_schedule.get("rests") or []
    normalized = []

    if isinstance(breaks, dict):
        breaks = [breaks]

    if isinstance(breaks, list):
        for item in breaks:
            if not isinstance(item, dict):
                continue

            break_start = (
