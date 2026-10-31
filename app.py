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
    gallery_change,
    list_docs,
    manage_booking,
    public_salon_by_slug,
    salon_ref,
    salons_for_owner,
    seed_salon,
    subscription_allows_booking,
    upsert,
)
from nailcraft.media import delete_image, upload_image

st.set_page_config(page_title="Nail Craft", page_icon="💅", layout="wide")

STATUS_LABEL = {
    "booked": "Reservada", "confirmed": "Confirmada", "completed": "Completada",
    "cancelled_by_client": "Cancelada por clienta", "cancelled_by_salon": "Cancelada por salón",
    "no_show": "No asistió",
}
DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def qp(name: str, default: str = "") -> str:
    value = st.query_params.get(name, default)
    return value[0] if isinstance(value, list) else value


def money(value) -> str:
    return f"${float(value or 0):,.2f}"


def staff_map(salon_id: str):
    return {x["id"]: x for x in list_docs(salon_id, "staff")}


def service_map(salon_id: str):
    return {x["id"]: x for x in list_docs(salon_id, "services")}


def public_page(slug: str):
    found = public_salon_by_slug(slug)
    if not found:
        st.error("Este salón no existe o el enlace no es correcto.")
        return
    salon_id, salon = found
    st.title(salon.get("name", "Nail Craft"))
    st.caption("Agenda tu cita en pocos pasos")
    gallery = sorted(list_docs(salon_id, "gallery"), key=lambda x: x.get("position", 99))
    if gallery:
        cols = st.columns(min(5, len(gallery)))
        for i, item in enumerate(gallery):
            cols[i % len(cols)].image(item["url"], use_container_width=True)

    if not subscription_allows_booking(salon):
        phone = salon.get("owner_phone", "")
        st.warning(f"La agenda en línea está temporalmente pausada. Comunícate con la dueña del salón{f' al {phone}' if phone else ''} para reservar.")
        return

    staff = [x for x in list_docs(salon_id, "staff") if x.get("active", True)]
    services = service_map(salon_id)
    if not staff or not services:
        st.info("Este salón todavía está preparando su agenda.")
        return

    st.subheader("1. Elige a tu colaboradora")
    labels = {x["id"]: x.get("name", "Colaboradora") for x in staff}
    chosen_staff_id = st.selectbox("Colaboradora", list(labels), format_func=labels.get)
    chosen_staff = next(x for x in staff if x["id"] == chosen_staff_id)
    if chosen_staff.get("photo_url"):
        st.image(chosen_staff["photo_url"], width=140)
    eligible = [services[sid] for sid in chosen_staff.get("service_ids", []) if sid in services and services[sid].get("active", True)]
    if not eligible:
        st.info("Esta colaboradora aún no tiene servicios disponibles.")
        return

    st.subheader("2. Elige servicio, día y hora")
    service_labels = {x["id"]: f"{x['name']} · {money(x['price'])} · {x['duration_minutes']} min" for x in eligible}
    service_id = st.selectbox("Servicio", list(service_labels), format_func=service_labels.get)
    service = services[service_id]
    day = st.date_input("Fecha", min_value=date.today(), max_value=date.today() + timedelta(days=90))
    starts = available_starts(salon_id, chosen_staff, service, day, salon.get("timezone", "America/Ciudad_Juarez"))
    if not starts:
        st.info("No hay horarios disponibles en este día.")
        return
    chosen_start = st.selectbox("Hora", starts, format_func=lambda x: x.strftime("%I:%M %p"))

    st.subheader("3. Tus datos")
    with st.form("booking"):
        name = st.text_input("Nombre completo")
        phone = st.text_input("WhatsApp / teléfono")
        email = st.text_input("Correo (opcional)")
        notes = st.text_area("Notas (opcional)")
        accepted = st.checkbox("Confirmo que puedo cancelar o reprogramar hasta 2 horas antes.")
        submit = st.form_submit_button("Reservar cita", type="primary")
    if submit:
        if len(name.strip()) < 2 or len(re.sub(r"\D", "", phone)) < 7 or not accepted:
            st.error("Completa nombre y teléfono, y acepta la política de cambios.")
            return
        end = chosen_start + timedelta(minutes=int(service["duration_minutes"]))
        try:
            appt_id, secret = create_booking_atomic(salon_id, salon, {
                "staff_id": chosen_staff_id, "staff_name": chosen_staff["name"],
                "service_id": service_id, "service_name": service["name"],
                "desk_id": chosen_staff.get("desk_id", ""), "start_at": chosen_start,
                "end_at": end, "price": float(service["price"]),
                "client_name": name.strip(), "client_phone": phone.strip(),
                "client_email": email.strip().lower(), "client_notes": notes.strip(),
                "source": "public_web", "notification_status": "pending",
            })
            base = st.context.url.split("?", 1)[0]
            manage_url = f"{base}?salon={slug}&manage={appt_id}&token={secret}"
            st.success("¡Tu cita quedó reservada!")
            st.info(f"Guarda este enlace para cancelar o reprogramar: {manage_url}")
        except ValueError as exc:
            st.error("Ese horario acaba de ocuparse. Elige otro." if str(exc) == "SLOT_TAKEN" else "La agenda se pausó; contacta a la dueña.")


def manage_public_booking(slug: str, appointment_id: str, token: str):
    found = public_salon_by_slug(slug)
    if not found:
        st.error("Enlace inválido.")
        return
    salon_id, salon = found
    snap = salon_ref(salon_id).collection("appointments").document(appointment_id).get()
    if not snap.exists:
        st.error("La cita no existe.")
        return
    item = snap.to_dict()
    st.title("Administrar cita")
    st.write(f"**{item.get('service_name')}** con {item.get('staff_name')}")
    st.write(item["start_at"].astimezone(ZoneInfo(salon.get("timezone", "America/Ciudad_Juarez"))).strftime("%d/%m/%Y · %I:%M %p"))
    if item.get("status") not in {"booked", "confirmed"}:
        st.info(f"Estado: {STATUS_LABEL.get(item.get('status'), item.get('status'))}")
        return
    if datetime.now(timezone.utc) > item["start_at"] - timedelta(hours=2):
        st.warning("Ya faltan menos de 2 horas. Contacta directamente al salón para solicitar un cambio.")
        return
    if st.button("Cancelar cita"):
        try:
            manage_booking(salon_id, appointment_id, token, "cancel")
            st.success("Cita cancelada.")
            st.rerun()
        except ValueError:
            st.error("No fue posible validar el enlace.")
    st.subheader("Reprogramar")
    staff = {x["id"]: x for x in list_docs(salon_id, "staff")}.get(item.get("staff_id"))
    service = {x["id"]: x for x in list_docs(salon_id, "services")}.get(item.get("service_id"))
    if staff and service:
        day = st.date_input("Nueva fecha", min_value=date.today(), max_value=date.today() + timedelta(days=90), key="reschedule_day")
        starts = [x for x in available_starts(salon_id, staff, service, day, salon.get("timezone", "America/Ciudad_Juarez")) if x != item["start_at"]]
        if starts:
            chosen = st.selectbox("Nueva hora", starts, format_func=lambda x: x.strftime("%I:%M %p"))
            if st.button("Confirmar nueva fecha", type="primary"):
                try:
                    manage_booking(salon_id, appointment_id, token, "reschedule", (chosen, chosen + timedelta(minutes=int(service["duration_minutes"]))))
                    st.success("Cita reprogramada."); st.rerun()
                except ValueError as exc:
                    st.error("Ese horario acaba de ocuparse." if str(exc) == "SLOT_TAKEN" else "No fue posible validar el enlace.")
        else:
            st.caption("No hay otros horarios disponibles ese día.")


def login_identity():
    if not st.user.is_logged_in:
        st.title("Panel de propietaria")
        st.write("Accede con la cuenta de Google autorizada para tu salón.")
        if st.button("Continuar con Google", type="primary"):
            st.login()
        st.stop()
    return st.user.email.lower()


def admin_dashboard(salon_id: str, salon: dict):
    tz = salon.get("timezone", "America/Ciudad_Juarez")
    st.header("Agenda administrativa")
    day = st.date_input("Día", value=date.today(), key="admin_day")
    start = datetime.combine(day, time.min, ZoneInfo(tz))
    items = appointments_between(salon_id, start, start + timedelta(days=1))
    desks = {x["id"]: x for x in list_docs(salon_id, "desks")}
    completed = [x for x in items if x.get("status") == "completed"]
    active_desks = max(1, len([x for x in desks.values() if x.get("active")]))
    capacity = active_desks * 8
    ratio = len(completed) / capacity
    color, label = ("🟢", "Alta") if ratio >= .7 else (("🟡", "Media") if ratio >= .35 else ("🔴", "Baja"))
    a, b, c = st.columns(3)
    a.metric("Citas del día", len(items)); b.metric("Completadas", len(completed)); c.metric("Ocupación completada", f"{color} {label} · {ratio:.0%}")
    staff = staff_map(salon_id)
    for item in items:
        with st.expander(f"{item['start_at'].astimezone(ZoneInfo(tz)).strftime('%I:%M %p')} · {item.get('client_name')} · {item.get('service_name')}"):
            st.write(f"Colaboradora: {staff.get(item.get('staff_id'), {}).get('name', item.get('staff_name', '—'))} · Tel: {item.get('client_phone', '—')}")
            options = list(STATUS_LABEL)
            current = item.get("status", "booked")
            new = st.selectbox("Estado", options, index=options.index(current) if current in options else 0, format_func=STATUS_LABEL.get, key=f"status_{item['id']}")
            if new != current:
                salon_ref(salon_id).collection("appointments").document(item["id"]).update({"status": new, "updated_at": firestore.SERVER_TIMESTAMP})
                st.rerun()


def admin_staff(salon_id: str):
    st.header("Colaboradoras y escritorios")
    desks = sorted(list_docs(salon_id, "desks"), key=lambda x: x.get("number", 0))
    for desk in desks:
        enabled = st.toggle(desk.get("name", desk["id"]), value=desk.get("active", False), key=f"desk_{desk['id']}")
        if enabled != desk.get("active", False):
            upsert(salon_id, "desks", desk["id"], {"active": enabled})
            st.rerun()
    services = list_docs(salon_id, "services")
    existing = list_docs(salon_id, "staff")
    choices = {x["id"]: x["name"] for x in existing}
    selected = st.selectbox("Editar perfil", [""] + list(choices), format_func=lambda x: "Nueva colaboradora" if x == "" else choices[x])
    item = next((x for x in existing if x["id"] == selected), {})
    with st.form("staff_form"):
        name = st.text_input("Nombre", item.get("name", ""))
        phone = st.text_input("Teléfono", item.get("phone", ""))
        active = st.checkbox("Perfil activo", item.get("active", True))
        desk_ids = [x["id"] for x in desks if x.get("active")]
        desk_id = st.selectbox("Escritorio", desk_ids, index=desk_ids.index(item.get("desk_id")) if item.get("desk_id") in desk_ids else 0) if desk_ids else ""
        service_ids = st.multiselect("Servicios", [x["id"] for x in services], default=item.get("service_ids", []), format_func=lambda x: next((s["name"] for s in services if s["id"] == x), x))
        photo = st.file_uploader("Foto", type=["jpg", "jpeg", "png", "webp"])
        schedule = {}
        st.caption("Horario semanal")
        for i, day_name in enumerate(DAYS):
            old = (item.get("schedule") or {}).get(str(i), {})
            cols = st.columns([2, 2, 2])
            works = cols[0].checkbox(day_name, bool(old), key=f"works_{selected}_{i}")
            start = cols[1].time_input("Entrada", time.fromisoformat(old.get("start", "09:00")), key=f"start_{selected}_{i}", label_visibility="collapsed")
            end = cols[2].time_input("Salida", time.fromisoformat(old.get("end", "18:00")), key=f"end_{selected}_{i}", label_visibility="collapsed")
            if works: schedule[str(i)] = {"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}
        save = st.form_submit_button("Guardar perfil", type="primary")
    if save:
        values = {"name": name.strip(), "phone": phone.strip(), "active": active, "desk_id": desk_id, "service_ids": service_ids, "schedule": schedule}
        if photo:
            media = upload_image(salon_id, "staff", photo)
            values.update({"photo_url": media["url"], "photo_path": media["storage_path"]})
        upsert(salon_id, "staff", selected or None, values)
        st.success("Perfil guardado."); st.rerun()


def admin_services(salon_id: str):
    st.header("Catálogo de servicios")
    items = list_docs(salon_id, "services")
    choices = {x["id"]: x["name"] for x in items}
    selected = st.selectbox("Editar", [""] + list(choices), format_func=lambda x: "Nuevo servicio" if not x else choices[x])
    item = next((x for x in items if x["id"] == selected), {})
    with st.form("service"):
        name = st.text_input("Servicio", item.get("name", ""))
        description = st.text_area("Descripción", item.get("description", ""))
        price = st.number_input("Precio", min_value=0.0, value=float(item.get("price", 0)), step=10.0)
        duration = st.number_input("Duración (minutos)", min_value=15, max_value=480, value=int(item.get("duration_minutes", 60)), step=15)
        active = st.checkbox("Disponible", item.get("active", True))
        save = st.form_submit_button("Guardar", type="primary")
    if save and name.strip():
        upsert(salon_id, "services", selected or None, {"name": name.strip(), "description": description.strip(), "price": price, "duration_minutes": duration, "active": active})
        st.success("Servicio guardado."); st.rerun()


def admin_gallery(salon_id: str):
    st.header("Galería")
    usage = salon_ref(salon_id).collection("usage").document(date.today().strftime("%Y-%m")).get().to_dict() or {}
    st.caption(f"10 espacios · {usage.get('gallery_changes', 0)}/3 operaciones usadas este mes")
    items = list_docs(salon_id, "gallery")
    cols = st.columns(5)
    for i, item in enumerate(items):
        with cols[i % 5]:
            st.image(item["url"], use_container_width=True)
            if st.button("Eliminar", key=f"del_{item['id']}"):
                try:
                    gallery_change(salon_id, "delete", image_id=item["id"])
                    delete_image(item.get("storage_path")); st.rerun()
                except ValueError: st.error("Límite mensual alcanzado.")
    upload = st.file_uploader("Agregar foto", type=["jpg", "jpeg", "png", "webp"], key="gallery_upload")
    if upload and st.button("Subir a galería", type="primary"):
        media = None
        try:
            media = upload_image(salon_id, "gallery", upload)
            gallery_change(salon_id, "add", media)
            st.success("Foto agregada."); st.rerun()
        except ValueError as exc:
            if media: delete_image(media.get("storage_path"))
            st.error("La galería está llena." if str(exc) == "CAPACITY_LIMIT" else "Ya se usaron las 3 operaciones del mes.")


def admin_settings(salon_id: str, salon: dict):
    st.header("Configuración del salón")
    with st.form("settings"):
        name = st.text_input("Nombre", salon.get("name", ""))
        phone = st.text_input("Teléfono de la dueña", salon.get("owner_phone", ""))
        timezone_name = st.text_input("Zona horaria", salon.get("timezone", "America/Ciudad_Juarez"))
        save = st.form_submit_button("Guardar", type="primary")
    if save:
        salon_ref(salon_id).update({"name": name.strip(), "owner_phone": phone.strip(), "timezone": timezone_name.strip(), "updated_at": firestore.SERVER_TIMESTAMP})
        st.success("Configuración guardada."); st.rerun()
    st.info(f"Suscripción: {salon.get('subscription_status', 'pendiente')} · vigencia: {salon.get('subscription_end', 'sin fecha')}")
    st.subheader("Automatización WhatsApp")
    st.write("Las citas se guardan con `notification_status = pending`. Un proceso externo debe leer esos eventos y enviarlos a la dueña mediante un proveedor autorizado. Esta versión no afirma ni simula envíos automáticos.")


def owner_panel():
    email = login_identity()
    master = email in [x.lower() for x in st.secrets.get("platform", {}).get("master_emails", [])]
    salons = all_salons() if master else salons_for_owner(email)
    if master:
        with st.sidebar.expander("Alta de salón"):
            with st.form("new_salon"):
                name = st.text_input("Nombre")
                slug = st.text_input("Subdominio / identificador")
                owner = st.text_input("Google de la propietaria")
                create = st.form_submit_button("Autorizar y crear")
            if create:
                if not name.strip() or not re.fullmatch(r"[a-z0-9-]{3,40}", slug.strip().lower()) or "@" not in owner:
                    st.error("Completa nombre, correo y un identificador de 3 a 40 caracteres (letras, números o guiones).")
                else:
                    try:
                        seed_salon(name, slug, owner, st.secrets.get("platform", {}).get("default_timezone", "America/Ciudad_Juarez")); st.rerun()
                    except ValueError:
                        st.error("Ese identificador ya está en uso.")
    if not salons:
        st.error("Tu cuenta Google no está autorizada para ningún salón.")
        if st.button("Cerrar sesión"): st.logout()
        return
    names = {sid: data.get("name", sid) for sid, data in salons}
    salon_id = st.sidebar.selectbox("Salón", names, format_func=names.get)
    salon = next(data for sid, data in salons if sid == salon_id)
    st.sidebar.write(email)
    if st.sidebar.button("Cerrar sesión"): st.logout()
    page = st.sidebar.radio("Sección", ["Agenda", "Colaboradoras", "Servicios", "Galería", "Configuración"])
    {"Agenda": admin_dashboard, "Colaboradoras": admin_staff, "Servicios": admin_services, "Galería": admin_gallery}.get(page, lambda sid: admin_settings(sid, salon))(salon_id)


mode = qp("mode")
slug = qp("salon")
if slug and qp("manage"):
    manage_public_booking(slug, qp("manage"), qp("token"))
elif slug:
    public_page(slug)
else:
    owner_panel()
