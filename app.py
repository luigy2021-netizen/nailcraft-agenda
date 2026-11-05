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
                item.get("start")
                or item.get("break_start")
                or item.get("rest_start")
            )
            break_end = (
                item.get("end")
                or item.get("break_end")
                or item.get("rest_end")
            )

            if break_start and break_end:
                normalized.append(
                    {
                        "start": break_start,
                        "end": break_end,
                    }
                )

    single_break_start = (
        day_schedule.get("break_start")
        or day_schedule.get("rest_start")
        or day_schedule.get("lunch_start")
    )
    single_break_end = (
        day_schedule.get("break_end")
        or day_schedule.get("rest_end")
        or day_schedule.get("lunch_end")
    )

    if single_break_start and single_break_end:
        normalized.append(
            {
                "start": single_break_start,
                "end": single_break_end,
            }
        )

    return normalized


def available_hours_for_day(staff_members: list[dict], day: date) -> float:
    weekday = str(day.weekday())
    total_minutes = 0

    for staff_member in staff_members:
        if not staff_member.get("active", True):
            continue

        day_schedule = (staff_member.get("schedule") or {}).get(weekday)
        if not isinstance(day_schedule, dict):
            continue

        work_start = time_to_minutes(day_schedule.get("start"))
        work_end = time_to_minutes(day_schedule.get("end"))

        if work_start is None or work_end is None or work_end <= work_start:
            continue

        available_minutes = work_end - work_start
        break_intervals = []

        for break_item in schedule_breaks(day_schedule):
            break_start = time_to_minutes(break_item.get("start"))
            break_end = time_to_minutes(break_item.get("end"))

            if (
                break_start is None
                or break_end is None
                or break_end <= break_start
            ):
                continue

            bounded_start = max(work_start, break_start)
            bounded_end = min(work_end, break_end)

            if bounded_end > bounded_start:
                break_intervals.append((bounded_start, bounded_end))

        break_intervals.sort()
        merged_breaks = []

        for break_start, break_end in break_intervals:
            if not merged_breaks or break_start > merged_breaks[-1][1]:
                merged_breaks.append([break_start, break_end])
            else:
                merged_breaks[-1][1] = max(
                    merged_breaks[-1][1],
                    break_end,
                )

        break_minutes = sum(
            break_end - break_start
            for break_start, break_end in merged_breaks
        )

        total_minutes += max(0, available_minutes - break_minutes)

    return total_minutes / 60


def completed_hours_for_day(
    completed_appointments: list[dict],
    day_start: datetime,
    day_end: datetime,
) -> float:
    total_seconds = 0.0

    for appointment in completed_appointments:
        appointment_start = appointment.get("start_at")
        appointment_end = appointment.get("end_at")

        if not isinstance(appointment_start, datetime):
            continue

        if not isinstance(appointment_end, datetime):
            duration_minutes = appointment.get("duration_minutes")
            try:
                appointment_end = appointment_start + timedelta(
                    minutes=float(duration_minutes)
                )
            except (TypeError, ValueError):
                continue

        bounded_start = max(appointment_start, day_start)
        bounded_end = min(appointment_end, day_end)

        if bounded_end > bounded_start:
            total_seconds += (bounded_end - bounded_start).total_seconds()

    return total_seconds / 3600


def public_page(slug: str):
    found = public_salon_by_slug(slug)

    if not found:
        st.error("Este salón no existe o el enlace no es correcto.")
        return

    salon_id, salon = found
    st.title(salon.get("name", "Nail Craft"))
    st.caption("Agenda tu cita en pocos pasos")

    collage = get_collage(salon_id)
    if collage and collage.get("url"):
        st.image(collage["url"], use_container_width=True)

    if not subscription_allows_booking(salon):
        phone = salon.get("owner_phone", "")
        phone_message = f" al {phone}" if phone else ""
        st.warning(
            "La agenda en línea está temporalmente pausada. "
            f"Comunícate con la dueña del salón{phone_message} para reservar."
        )
        return

    staff = [
        x
        for x in list_docs(salon_id, "staff")
        if x.get("active", True)
    ]
    services = service_map(salon_id)

    if not staff or not services:
        st.info("Este salón todavía está preparando su agenda.")
        return

    st.subheader("1. Elige a tu colaboradora")

    labels = {
        x["id"]: x.get("name", "Colaboradora")
        for x in staff
    }

    chosen_staff_id = st.selectbox(
        "Colaboradora",
        list(labels),
        format_func=labels.get,
    )

    chosen_staff = next(
        x for x in staff if x["id"] == chosen_staff_id
    )

    if chosen_staff.get("photo_url"):
        st.image(chosen_staff["photo_url"], width=140)

    eligible = [
        services[service_id]
        for service_id in chosen_staff.get("service_ids", [])
        if (
            service_id in services
            and services[service_id].get("active", True)
        )
    ]

    if not eligible:
        st.info("Esta colaboradora aún no tiene servicios disponibles.")
        return

    st.subheader("2. Elige servicio, día y hora")

    service_labels = {
        x["id"]: (
            f"{x['name']} · {money(x['price'])} · "
            f"{x['duration_minutes']} min"
        )
        for x in eligible
    }

    service_id = st.selectbox(
        "Servicio",
        list(service_labels),
        format_func=service_labels.get,
    )
    service = services[service_id]

    day = st.date_input(
        "Fecha",
        min_value=date.today(),
        max_value=date.today() + timedelta(days=90),
    )

    starts = available_starts(
        salon_id,
        chosen_staff,
        service,
        day,
        salon.get("timezone", "America/Ciudad_Juarez"),
    )

    if not starts:
        st.info("No hay horarios disponibles en este día.")
        return

    chosen_start = st.selectbox(
        "Hora",
        starts,
        format_func=lambda value: value.strftime("%I:%M %p"),
    )

    st.subheader("3. Tus datos")

    with st.form("booking"):
        name = st.text_input("Nombre completo")
        phone = st.text_input("WhatsApp / teléfono")
        email = st.text_input("Correo (opcional)")
        notes = st.text_area("Notas (opcional)")
        accepted = st.checkbox(
            "Confirmo que puedo cancelar o reprogramar "
            "hasta 2 horas antes."
        )
        submit = st.form_submit_button(
            "Reservar cita",
            type="primary",
        )

    if submit:
        valid_name = len(name.strip()) >= 2
        valid_phone = len(re.sub(r"\D", "", phone)) >= 7

        if not valid_name or not valid_phone or not accepted:
            st.error(
                "Completa nombre y teléfono, y acepta "
                "la política de cambios."
            )
            return

        end = chosen_start + timedelta(
            minutes=int(service["duration_minutes"])
        )

        try:
            appt_id, secret = create_booking_atomic(
                salon_id,
                salon,
                {
                    "staff_id": chosen_staff_id,
                    "staff_name": chosen_staff["name"],
                    "service_id": service_id,
                    "service_name": service["name"],
                    "desk_id": chosen_staff.get("desk_id", ""),
                    "start_at": chosen_start,
                    "end_at": end,
                    "price": float(service["price"]),
                    "client_name": name.strip(),
                    "client_phone": phone.strip(),
                    "client_email": email.strip().lower(),
                    "client_notes": notes.strip(),
                    "source": "public_web",
                    "notification_status": "pending",
                },
            )

            base = st.context.url.split("?", 1)[0]
            manage_url = (
                f"{base}?salon={slug}&manage={appt_id}&token={secret}"
            )

            st.success("¡Tu cita quedó reservada!")
            st.info(
                "Guarda este enlace para cancelar o reprogramar: "
                f"{manage_url}"
            )
        except ValueError as exc:
            if str(exc) == "SLOT_TAKEN":
                st.error(
                    "Ese horario acaba de ocuparse. Elige otro."
                )
            else:
                st.error(
                    "La agenda se pausó; contacta a la dueña."
                )


def manage_public_booking(
    slug: str,
    appointment_id: str,
    token: str,
):
    found = public_salon_by_slug(slug)

    if not found:
        st.error("Enlace inválido.")
        return

    salon_id, salon = found
    snap = (
        salon_ref(salon_id)
        .collection("appointments")
        .document(appointment_id)
        .get()
    )

    if not snap.exists:
        st.error("La cita no existe.")
        return

    item = snap.to_dict()
    timezone_name = salon.get(
        "timezone",
        "America/Ciudad_Juarez",
    )

    st.title("Administrar cita")
    st.write(
        f"**{item.get('service_name')}** "
        f"con {item.get('staff_name')}"
    )
    st.write(
        item["start_at"]
        .astimezone(ZoneInfo(timezone_name))
        .strftime("%d/%m/%Y · %I:%M %p")
    )

    if item.get("status") not in {"booked", "confirmed"}:
        status = STATUS_LABEL.get(
            item.get("status"),
            item.get("status"),
        )
        st.info(f"Estado: {status}")
        return

    if datetime.now(timezone.utc) > (
        item["start_at"] - timedelta(hours=2)
    ):
        st.warning(
            "Ya faltan menos de 2 horas. Contacta directamente "
            "al salón para solicitar un cambio."
        )
        return

    if st.button("Cancelar cita"):
        try:
            manage_booking(
                salon_id,
                appointment_id,
                token,
                "cancel",
            )
            st.success("Cita cancelada.")
            st.rerun()
        except ValueError:
            st.error("No fue posible validar el enlace.")

    st.subheader("Reprogramar")

    staff = {
        x["id"]: x
        for x in list_docs(salon_id, "staff")
    }.get(item.get("staff_id"))

    service = {
        x["id"]: x
        for x in list_docs(salon_id, "services")
    }.get(item.get("service_id"))

    if staff and service:
        day = st.date_input(
            "Nueva fecha",
            min_value=date.today(),
            max_value=date.today() + timedelta(days=90),
            key="reschedule_day",
        )

        starts = [
            value
            for value in available_starts(
                salon_id,
                staff,
                service,
                day,
                timezone_name,
            )
            if value != item["start_at"]
        ]

        if starts:
            chosen = st.selectbox(
                "Nueva hora",
                starts,
                format_func=lambda value: value.strftime("%I:%M %p"),
            )

            if st.button(
                "Confirmar nueva fecha",
                type="primary",
            ):
                new_end = chosen + timedelta(
                    minutes=int(service["duration_minutes"])
                )

                try:
                    manage_booking(
                        salon_id,
                        appointment_id,
                        token,
                        "reschedule",
                        (chosen, new_end),
                    )
                    st.success("Cita reprogramada.")
                    st.rerun()
                except ValueError as exc:
                    if str(exc) == "SLOT_TAKEN":
                        st.error(
                            "Ese horario acaba de ocuparse."
                        )
                    else:
                        st.error(
                            "No fue posible validar el enlace."
                        )
        else:
            st.caption(
                "No hay otros horarios disponibles ese día."
            )


def login_identity():
    if not st.user.is_logged_in:
        st.title("Panel de propietaria")
        st.write(
            "Accede con la cuenta de Google autorizada "
            "para tu salón."
        )

        if st.button(
            "Continuar con Google",
            type="primary",
        ):
            st.login()

        st.stop()

    return st.user.email.lower()


def admin_dashboard(salon_id: str, salon: dict):
    timezone_name = salon.get(
        "timezone",
        "America/Ciudad_Juarez",
    )

    st.header("Agenda administrativa")

    day = st.date_input(
        "Día",
        value=date.today(),
        key="admin_day",
    )

    day_start = datetime.combine(
        day,
        time.min,
        ZoneInfo(timezone_name),
    )
    day_end = day_start + timedelta(days=1)

    items = appointments_between(
        salon_id,
        day_start,
        day_end,
    )

    completed = [
        item
        for item in items
        if item.get("status") == "completed"
    ]

    staff_members = list_docs(salon_id, "staff")

    completed_hours = completed_hours_for_day(
        completed,
        day_start,
        day_end,
    )
    available_hours = available_hours_for_day(
        staff_members,
        day,
    )

    if available_hours > 0:
        productivity = completed_hours / available_hours
    else:
        productivity = 0.0

    productivity = max(0.0, min(productivity, 1.0))

    if productivity >= 0.80:
        color = "🟢"
        label = "Alta"
    elif productivity >= 0.50:
        color = "🟡"
        label = "Media"
    else:
        color = "🔴"
        label = "Baja"

    column_a, column_b, column_c = st.columns(3)

    column_a.metric(
        "Citas del día",
        len(items),
    )
    column_b.metric(
        "Completadas",
        len(completed),
    )
    column_c.metric(
        "Productividad",
        f"{color} {label} · {productivity:.0%}",
        help=(
            f"{completed_hours:.2f} horas completadas de "
            f"{available_hours:.2f} horas disponibles. "
            "Los descansos configurados están descontados."
        ),
    )

    staff = staff_map(salon_id)

    for item in items:
        appointment_time = (
            item["start_at"]
            .astimezone(ZoneInfo(timezone_name))
            .strftime("%I:%M %p")
        )

        client_name = item.get("client_name")
        service_name = item.get("service_name")

        with st.expander(
            f"{appointment_time} · {client_name} · {service_name}"
        ):
            staff_name = staff.get(
                item.get("staff_id"),
                {},
            ).get(
                "name",
                item.get("staff_name", "—"),
            )

            st.write(
                f"Colaboradora: {staff_name} · "
                f"Tel: {item.get('client_phone', '—')}"
            )

            options = list(STATUS_LABEL)
            current = item.get("status", "booked")

            new = st.selectbox(
                "Estado",
                options,
                index=(
                    options.index(current)
                    if current in options
                    else 0
                ),
                format_func=STATUS_LABEL.get,
                key=f"status_{item['id']}",
            )

            if new != current:
                (
                    salon_ref(salon_id)
                    .collection("appointments")
                    .document(item["id"])
                    .update(
                        {
                            "status": new,
                            "updated_at": firestore.SERVER_TIMESTAMP,
                        }
                    )
                )
                st.rerun()


def admin_staff(salon_id: str):
    st.header("Colaboradoras y escritorios")

    desks = sorted(
        list_docs(salon_id, "desks"),
        key=lambda item: item.get("number", 0),
    )

    for desk in desks:
        enabled = st.toggle(
            desk.get("name", desk["id"]),
            value=desk.get("active", False),
            key=f"desk_{desk['id']}",
        )

        if enabled != desk.get("active", False):
            upsert(
                salon_id,
                "desks",
                desk["id"],
                {"active": enabled},
            )
            st.rerun()

    services = list_docs(salon_id, "services")
    existing = list_docs(salon_id, "staff")

    choices = {
        item["id"]: item["name"]
        for item in existing
    }

    selected = st.selectbox(
        "Editar perfil",
        [""] + list(choices),
        format_func=lambda value: (
            "Nueva colaboradora"
            if value == ""
            else choices[value]
        ),
    )

    item = next(
        (
            staff_member
            for staff_member in existing
            if staff_member["id"] == selected
        ),
        {},
    )

    with st.form("staff_form"):
        name = st.text_input(
            "Nombre",
            item.get("name", ""),
        )
        phone = st.text_input(
            "Teléfono",
            item.get("phone", ""),
        )
        active = st.checkbox(
            "Perfil activo",
            item.get("active", True),
        )

        desk_ids = [
            desk["id"]
            for desk in desks
            if desk.get("active")
        ]

        if desk_ids:
            current_desk = item.get("desk_id")
            desk_index = (
                desk_ids.index(current_desk)
                if current_desk in desk_ids
                else 0
            )

            desk_id = st.selectbox(
                "Escritorio",
                desk_ids,
                index=desk_index,
            )
        else:
            desk_id = ""

        service_ids = st.multiselect(
            "Servicios",
            [service["id"] for service in services],
            default=item.get("service_ids", []),
            format_func=lambda value: next(
                (
                    service["name"]
                    for service in services
                    if service["id"] == value
                ),
                value,
            ),
        )

        photo = st.file_uploader(
            "Foto",
            type=["jpg", "jpeg", "png", "webp"],
        )

        schedule = {}
        st.caption("Horario semanal")

        for index, day_name in enumerate(DAYS):
            old = (
                item.get("schedule") or {}
            ).get(str(index), {})

            columns = st.columns([2, 2, 2])

            works = columns[0].checkbox(
                day_name,
                bool(old),
                key=f"works_{selected}_{index}",
            )

            start = columns[1].time_input(
                "Entrada",
                time.fromisoformat(old.get("start", "09:00")),
                key=f"start_{selected}_{index}",
                label_visibility="collapsed",
            )

            end = columns[2].time_input(
                "Salida",
                time.fromisoformat(old.get("end", "18:00")),
                key=f"end_{selected}_{index}",
                label_visibility="collapsed",
            )

            if works:
                day_schedule = {
                    "start": start.strftime("%H:%M"),
                    "end": end.strftime("%H:%M"),
                }

                for break_key in (
                    "breaks",
                    "rests",
                    "break_start",
                    "break_end",
                    "rest_start",
                    "rest_end",
                    "lunch_start",
                    "lunch_end",
                ):
                    if break_key in old:
                        day_schedule[break_key] = old[break_key]

                schedule[str(index)] = day_schedule

        save = st.form_submit_button(
            "Guardar perfil",
            type="primary",
        )

    if save:
        values = {
            "name": name.strip(),
            "phone": phone.strip(),
            "active": active,
            "desk_id": desk_id,
            "service_ids": service_ids,
            "schedule": schedule,
        }

        if photo:
            media = upload_image(
                salon_id,
                "staff",
                photo,
            )
            values.update(
                {
                    "photo_url": media["url"],
                    "photo_path": media["storage_path"],
                }
            )

        upsert(
            salon_id,
            "staff",
            selected or None,
            values,
        )

        st.success("Perfil guardado.")
        st.rerun()


def admin_services(salon_id: str):
    st.header("Catálogo de servicios")

    items = list_docs(salon_id, "services")
    choices = {
        item["id"]: item["name"]
        for item in items
    }

    selected = st.selectbox(
        "Editar",
        [""] + list(choices),
        format_func=lambda value: (
            "Nuevo servicio"
            if not value
            else choices[value]
        ),
    )

    item = next(
        (
            service
            for service in items
            if service["id"] == selected
        ),
        {},
    )

    with st.form("service"):
        name = st.text_input(
            "Servicio",
            item.get("name", ""),
        )
        description = st.text_area(
            "Descripción",
            item.get("description", ""),
        )
        price = st.number_input(
            "Precio",
            min_value=0.0,
            value=float(item.get("price", 0)),
            step=10.0,
        )
        duration = st.number_input(
            "Duración (minutos)",
            min_value=15,
            max_value=480,
            value=int(item.get("duration_minutes", 60)),
            step=15,
        )
        active = st.checkbox(
            "Disponible",
            item.get("active", True),
        )
        save = st.form_submit_button(
            "Guardar",
            type="primary",
        )

    if save and name.strip():
        upsert(
            salon_id,
            "services",
            selected or None,
            {
                "name": name.strip(),
                "description": description.strip(),
                "price": price,
                "duration_minutes": duration,
                "active": active,
            },
        )

        st.success("Servicio guardado.")
        st.rerun()


def admin_collage(salon_id: str):
    st.header("Collage del salón")
    st.caption(
        "Una sola imagen panorámica, recomendada en "
        "1800 × 900 px. Puedes reemplazarla cuando quieras."
    )

    current = get_collage(salon_id)

    if current and current.get("url"):
        st.image(
            current["url"],
            use_container_width=True,
        )

        if st.button("Quitar collage"):
            remove_collage(salon_id)
            st.success("Collage eliminado.")
            st.rerun()

    upload = st.file_uploader(
        "Nuevo collage",
        type=["jpg", "jpeg", "png", "webp"],
        key="collage_upload",
    )

    if upload and st.button(
        "Guardar collage",
        type="primary",
    ):
        try:
            media = upload_image(
                salon_id,
                "collage",
                upload,
            )
            save_collage(salon_id, media)
            st.success("Collage actualizado.")
            st.rerun()
        except ValueError:
            st.error(
                "La imagen no pudo comprimirse. Utiliza un collage "
                "JPG o WebP de hasta 1800 × 900 px."
            )


def admin_settings(salon_id: str, salon: dict):
    st.header("Configuración del salón")

    with st.form("settings"):
        name = st.text_input(
            "Nombre",
            salon.get("name", ""),
        )
        phone = st.text_input(
            "Teléfono de la dueña",
            salon.get("owner_phone", ""),
        )
        timezone_name = st.text_input(
            "Zona horaria",
            salon.get(
                "timezone",
                "America/Ciudad_Juarez",
            ),
        )
        save = st.form_submit_button(
            "Guardar",
            type="primary",
        )

    if save:
        salon_ref(salon_id).update(
            {
                "name": name.strip(),
                "owner_phone": phone.strip(),
                "timezone": timezone_name.strip(),
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
        )

        st.success("Configuración guardada.")
        st.rerun()

    subscription_status = salon.get(
        "subscription_status",
        "pendiente",
    )
    subscription_end = salon.get(
        "subscription_end",
        "sin fecha",
    )

    st.info(
        f"Suscripción: {subscription_status} · "
        f"vigencia: {subscription_end}"
    )

    st.subheader("Automatización WhatsApp")
    st.write(
        "Las citas se guardan con "
        "`notification_status = pending`. Un proceso externo "
        "debe leer esos eventos y enviarlos a la dueña mediante "
        "un proveedor autorizado. Esta versión no afirma ni "
        "simula envíos automáticos."
    )


def owner_panel():
    email = login_identity()

    master_emails = st.secrets.get(
        "platform",
        {},
    ).get(
        "master_emails",
        [],
    )

    master = email in [
        master_email.lower()
        for master_email in master_emails
    ]

    salons = (
        all_salons()
        if master
        else salons_for_owner(email)
    )

    if master:
        with st.sidebar.expander("Alta de salón"):
            with st.form("new_salon"):
                name = st.text_input("Nombre")
                slug = st.text_input(
                    "Subdominio / identificador"
                )
                owner = st.text_input(
                    "Google de la propietaria"
                )
                create = st.form_submit_button(
                    "Autorizar y crear"
                )

            if create:
                valid_slug = re.fullmatch(
                    r"[a-z0-9-]{3,40}",
                    slug.strip().lower(),
                )

                if (
                    not name.strip()
                    or not valid_slug
                    or "@" not in owner
                ):
                    st.error(
                        "Completa nombre, correo y un identificador "
                        "de 3 a 40 caracteres "
                        "(letras, números o guiones)."
                    )
                else:
                    default_timezone = st.secrets.get(
                        "platform",
                        {},
                    ).get(
                        "default_timezone",
                        "America/Ciudad_Juarez",
                    )

                    try:
                        seed_salon(
                            name,
                            slug,
                            owner,
                            default_timezone,
                        )
                        st.rerun()
                    except ValueError:
                        st.error(
                            "Ese identificador ya está en uso."
                        )

    if not salons:
        st.error(
            "Tu cuenta Google no está autorizada "
            "para ningún salón."
        )

        if st.button("Cerrar sesión"):
            st.logout()

        return

    names = {
        salon_id: salon_data.get("name", salon_id)
        for salon_id, salon_data in salons
    }

    salon_id = st.sidebar.selectbox(
        "Salón",
        names,
        format_func=names.get,
    )

    salon = next(
        salon_data
        for current_id, salon_data in salons
        if current_id == salon_id
    )

    st.sidebar.write(email)

    if st.sidebar.button("Cerrar sesión"):
        st.logout()

    page = st.sidebar.radio(
        "Sección",
        [
            "Agenda",
            "Colaboradoras",
            "Servicios",
            "Collage",
            "Configuración",
        ],
    )

    pages = {
        "Agenda": admin_dashboard,
        "Colaboradoras": admin_staff,
        "Servicios": admin_services,
        "Collage": admin_collage,
    }

    selected_page = pages.get(
        page,
        lambda current_salon_id: admin_settings(
            current_salon_id,
            salon,
        ),
    )

    selected_page(salon_id)


mode = qp("mode")
slug = qp("salon")

if slug and qp("manage"):
    manage_public_booking(
        slug,
        qp("manage"),
        qp("token"),
    )
elif slug:
    public_page(slug)
else:
    owner_panel()
