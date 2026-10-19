import base64
import json
from datetime import date, datetime, time, timedelta
from html import escape
from pathlib import Path
from urllib.parse import quote

import firebase_admin
import streamlit as st
from firebase_admin import credentials, firestore


# =====================================================
# CONFIGURACIÓN GENERAL
# =====================================================

st.set_page_config(
    page_title="Nailcraft | Agenda",
    page_icon="💅",
    layout="centered",
    initial_sidebar_state="collapsed",
)

BASE_DIR = Path(__file__).parent

APP_URL = st.secrets.get(
    "app_url",
    "https://nailcraft-agenda.streamlit.app",
)

WHATSAPP_NEGOCIO = "5216563005504"
CORREO_DUENO = str(st.secrets.get("owner_email", "")).strip().lower()

SERVICIOS = {"Manicure": 120}

TECNICAS = [
    "Técnica 1",
    "Técnica 2",
    "Técnica 3",
]

COLECCION_NEGOCIOS = "nailcraft_businesses"
COLECCION_CITAS = "nailcraft_appointments"

PLANES = {
    "Starter": [
        "Agenda personalizada con logo e imagen del negocio",
        "Bloqueo automático de horarios empalmados",
        "Comentarios adicionales en cada reservación",
        "Confirmación de cita por WhatsApp",
    ],
    "Business": [
        "Todo lo incluido en Starter",
        "Promociones por recomendación",
        "Enlace directo para compartir tu agenda",
        "Flyer promocional en el encabezado",
    ],
    "Premium": [
        "Todo lo incluido en Business",
        "Flyers promocionales nuevos cada mes",
        "Cancelación y reprogramación de citas",
        "Bloqueos por vacaciones o días inhábiles",
        "Administración avanzada de disponibilidad",
    ],
}

HORA_APERTURA = time(9, 0)
HORA_CIERRE = time(21, 0)
DURACION_PRUEBA_DIAS = 15


# =====================================================
# ESTILOS
# =====================================================

def aplicar_estilos():
    st.markdown(
        """
        <style>
        @import url(
            'https://fonts.googleapis.com/css2?'
            'family=DM+Sans:wght@400;500;600;700&'
            'family=Space+Grotesk:wght@500;600;700&display=swap'
        );

        :root {
            --bg: #fff9fd;
            --surface: rgba(255,255,255,.94);
            --surface-2: #fff4fc;
            --field: #ffffff;
            --text: #27152d;
            --muted: #735f78;
            --aqua: #b20bd4;
            --line: rgba(104,26,117,.13);
        }

        .stApp,
        [data-testid="stAppViewContainer"],
        .main {
            background:
                radial-gradient(
                    circle at 50% -10%,
                    rgba(222,92,206,.16),
                    transparent 34rem
                ),
                var(--bg) !important;
            color: var(--text) !important;
            font-family: "DM Sans", sans-serif;
        }

        #MainMenu, footer, header {
            visibility: hidden;
        }

        .block-container {
            width: 100%;
            max-width: 430px;
            padding: .8rem 1rem 5rem !important;
            margin: 0 auto;
        }

        h1, h2, h3 {
            color: var(--text) !important;
            font-family: "Space Grotesk", sans-serif !important;
            letter-spacing: -.035em;
        }

        h2 {
            font-size: clamp(1.75rem,5vw,2.35rem) !important;
            line-height: 1.08 !important;
        }

        p, li, .stCaption {
            color: var(--muted) !important;
        }

        .hero img {
            display: block;
            width: 100%;
            border-radius: 26px;
            border: 1px solid var(--line);
            box-shadow: 0 24px 70px rgba(100,20,105,.18);
        }

        .section {
            margin: 2.7rem 0 1rem;
        }

        .eyebrow {
            color: var(--aqua);
            font-weight: 700;
            font-size: .72rem;
            letter-spacing: .13em;
            text-transform: uppercase;
            margin-bottom: .5rem;
        }

        .glass-card,
        .selected-state,
        .booking-summary {
            margin: .9rem 0;
            padding: 1.15rem 1.2rem;
            border: 1px solid var(--line);
            border-radius: 22px;
            background: var(--surface);
            box-shadow: 0 18px 50px rgba(100,20,105,.10);
        }

        .selected-state {
            padding: .8rem 1rem;
            color: var(--muted);
            font-size: .92rem;
        }

        .selected-state b,
        .booking-summary strong {
            color: var(--text);
        }

        .accent {
            color: var(--aqua);
        }

        div[data-testid="stWidgetLabel"] p {
            color: var(--muted) !important;
            font-weight: 600 !important;
        }

        [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        [data-testid="stDateInput"] input,
        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea,
        div[data-baseweb="input"] > div {
            background-color: var(--field) !important;
            color: var(--text) !important;
            border: 1px solid var(--line) !important;
            border-radius: 15px !important;
            box-shadow: none !important;
        }

        [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        [data-testid="stDateInput"] input,
        [data-testid="stTextInput"] input {
            min-height: 52px !important;
        }

        [data-testid="stTextArea"] textarea {
            min-height: 84px !important;
        }

        div[data-baseweb="popover"],
        ul[role="listbox"],
        [role="option"] {
            background: #ffffff !important;
            color: var(--text) !important;
        }

        .stButton > button {
            min-height: 54px !important;
            border: 1px solid var(--line) !important;
            border-radius: 16px !important;
            background: var(--surface-2) !important;
            color: var(--text) !important;
            font-family: "DM Sans", sans-serif !important;
            font-weight: 650 !important;
        }

        .stButton > button[kind="primary"] {
            border-color: transparent !important;
            background: linear-gradient(135deg,#d823e5,#8b05bd) !important;
            color: #ffffff !important;
        }

        [class*="st-key-servicio_"] button {
            min-height: 72px !important;
            text-align: left !important;
            justify-content: flex-start !important;
        }

        [class*="st-key-hora_"] button {
            min-height: 44px !important;
            border-radius: 999px !important;
            font-size: .86rem !important;
        }

        [data-testid="stAlert"] {
            border-radius: 16px !important;
            border: 1px solid var(--line) !important;
            background: rgba(255,255,255,.70) !important;
        }

        .owner-header {
            padding: 1rem 0 .35rem;
        }

        .owner-header h1 {
            margin: 0 !important;
            font-size: clamp(2rem,8vw,3rem) !important;
        }

        .metric-card {
            min-height: 112px;
            padding: 1rem;
            border: 1px solid var(--line);
            border-radius: 20px;
            background: var(--surface);
        }

        .metric-card .value {
            color: var(--text);
            font-family: "Space Grotesk", sans-serif;
            font-size: 1.9rem;
            font-weight: 700;
        }

        .metric-card .label {
            color: var(--muted);
            font-size: .8rem;
        }

        .appointment-card {
            margin: .65rem 0;
            padding: .9rem 1rem;
            border-left: 3px solid var(--aqua);
            border-radius: 0 16px 16px 0;
            background: rgba(255,255,255,.78);
        }

        .appointment-card strong {
            color: var(--text);
        }

        .appointment-card .meta {
            color: var(--muted);
            font-size: .84rem;
        }

        @media (max-width: 640px) {
            .block-container {
                max-width: 100%;
                padding-left: .78rem !important;
                padding-right: .78rem !important;
            }

            .hero img {
                border-radius: 20px;
            }

            [class*="st-key-plan_"] button {
                min-height: 50px !important;
                padding: .25rem !important;
                font-size: .72rem !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =====================================================
# FIREBASE / FIRESTORE
# =====================================================

@st.cache_resource
def get_db():
    contenido = base64.b64decode(
        str(st.secrets["firebase_service_account_b64"])
    ).decode("utf-8")

    informacion = json.loads(contenido)

    if not firebase_admin._apps:
        credencial = credentials.Certificate(informacion)
        firebase_admin.initialize_app(credencial)

    return firestore.client()


def texto_seguro(valor):
    return escape(str(valor or "").strip())


def datos_usuario():
    if not st.user.is_logged_in:
        return {}

    return st.user.to_dict()


def id_usuario_actual():
    usuario = datos_usuario()
    return str(
        usuario.get("sub")
        or usuario.get("email")
        or ""
    ).strip()


def usuario_es_dueno():
    correo = str(datos_usuario().get("email", "")).strip().lower()
    return bool(correo) and (
        not CORREO_DUENO or correo == CORREO_DUENO
    )


def obtener_negocio(negocio_id):
    if not negocio_id:
        return None

    documento = (
        get_db()
        .collection(COLECCION_NEGOCIOS)
        .document(negocio_id)
        .get()
    )

    if not documento.exists:
        return None

    negocio = documento.to_dict() or {}
    negocio["id"] = documento.id
    return negocio


def obtener_negocio_del_dueno():
    usuario_id = id_usuario_actual()

    if not usuario_id:
        return None

    return obtener_negocio(usuario_id)


def obtener_negocio_publico():
    documentos = (
        get_db()
        .collection(COLECCION_NEGOCIOS)
        .limit(1)
        .stream()
    )

    for documento in documentos:
        negocio = documento.to_dict() or {}
        negocio["id"] = documento.id
        return negocio

    return None


def crear_negocio(nombre, celular):
    usuario = datos_usuario()
    usuario_id = id_usuario_actual()

    if not usuario_id:
        raise ValueError("No hay un usuario autenticado.")

    datos = {
        "owner_uid": usuario_id,
        "owner_email": str(usuario.get("email", "")).strip(),
        "owner_name": str(usuario.get("name", "")).strip(),
        "business_name": nombre.strip(),
        "phone": celular.strip(),
        "plan": "Starter",
        "trial_days": DURACION_PRUEBA_DIAS,
        "trial_started_at": datetime.now().isoformat(),
        "trial_ends_at": (
            datetime.now() + timedelta(days=DURACION_PRUEBA_DIAS)
        ).isoformat(),
        "created_at": firestore.SERVER_TIMESTAMP,
        "active": True,
    }

    (
        get_db()
        .collection(COLECCION_NEGOCIOS)
        .document(usuario_id)
        .set(datos)
    )


def dias_prueba_restantes(negocio):
    valor = str(negocio.get("trial_ends_at", "")).strip()
    if not valor:
        return DURACION_PRUEBA_DIAS

    try:
        termina = datetime.fromisoformat(valor)
    except ValueError:
        return DURACION_PRUEBA_DIAS

    diferencia = termina - datetime.now()
    return max(0, diferencia.days + (1 if diferencia.seconds else 0))


def consulta_citas(negocio_id):
    if not negocio_id:
        return []

    documentos = (
        get_db()
        .collection(COLECCION_CITAS)
        .where("business_id", "==", negocio_id)
        .stream()
    )

    return [documento.to_dict() or {} for documento in documentos]


def preparar_cita(cita):
    fecha_texto = str(cita.get("fecha", ""))
    hora_texto = str(cita.get("hora", ""))

    try:
        cita["inicio"] = datetime.strptime(
            f"{fecha_texto} {hora_texto}",
            "%Y-%m-%d %I:%M %p",
        )
    except (TypeError, ValueError):
        cita["inicio"] = None

    try:
        cita["duracion_min"] = int(cita.get("duracion", 0))
    except (TypeError, ValueError):
        cita["duracion_min"] = 0

    return cita


def obtener_citas(negocio_id):
    return [
        preparar_cita(cita)
        for cita in consulta_citas(negocio_id)
    ]


def guardar_cita(datos):
    referencia = get_db().collection(COLECCION_CITAS).document()

    datos = dict(datos)
    datos["id"] = referencia.id
    datos["created_at"] = firestore.SERVER_TIMESTAMP

    referencia.set(datos)
    return referencia.id


def se_empalma(inicio_a, fin_a, inicio_b, fin_b):
    return inicio_a < fin_b and inicio_b < fin_a


def horarios_disponibles(
    fecha,
    duracion,
    tecnica,
    negocio_id=None,
):
    if fecha.weekday() == 6:
        return []

    citas = []

    if negocio_id:
        for cita in obtener_citas(negocio_id):
            if (
                cita.get("fecha") == str(fecha)
                and str(cita.get("estado", "")).lower()
                != "cancelada"
                and cita.get("inicio")
                and cita.get("tecnica") == tecnica
            ):
                inicio = cita["inicio"]
                termino = inicio + timedelta(
                    minutes=cita["duracion_min"]
                )
                citas.append((inicio, termino))

    disponibles = []
    actual = datetime.combine(fecha, HORA_APERTURA)
    cierre = datetime.combine(fecha, HORA_CIERRE)
    ahora = datetime.now()

    while actual < cierre:
        fin = actual + timedelta(minutes=duracion)

        ocupado = any(
            se_empalma(actual, fin, inicio, termino)
            for inicio, termino in citas
        )

        if (
            fin <= cierre
            and actual > ahora
            and not ocupado
        ):
            disponibles.append(actual.strftime("%I:%M %p"))

        actual += timedelta(minutes=30)

    return disponibles


def duracion_legible(minutos):
    if minutos < 60:
        return f"{minutos} min"

    if minutos == 60:
        return "1 hora"

    horas = minutos / 60

    if horas.is_integer():
        return f"{int(horas)} horas"

    return f"{minutos} min"


# =====================================================
# AGENDA PÚBLICA
# =====================================================

def mostrar_experiencia(negocio=None):
    negocio_id = negocio.get("id") if negocio else None

    introduccion = (
        '<div class="eyebrow">Bienvenida a Nailcraft</div>'
        "<h2>Agenda tu cita y disfruta unas uñas increíbles</h2>"
        "<p>Lunes a sábado · 9:00 a. m. a 9:00 p. m.</p>"
    )

    st.markdown(
        f'<section class="section">{introduccion}</section>',
        unsafe_allow_html=True,
    )

    giro = "Salón de uñas"
    servicios = SERVICIOS

    st.markdown(
        f'<div class="selected-state">'
        f'<span class="accent">01</span> &nbsp; '
        f'<b>Nuestros servicios</b> · Elige el servicio'
        f'</div>',
        unsafe_allow_html=True,
    )

    nombres = list(servicios)

    for i in range(0, len(nombres), 2):
        columnas = st.columns(2, gap="small")

        for j, servicio_nombre in enumerate(nombres[i:i + 2]):
            minutos = servicios[servicio_nombre]
            seleccionado = (
                st.session_state.get("servicio_demo")
                == servicio_nombre
            )

            etiqueta = (
                f"{'✓  ' if seleccionado else ''}"
                f"{servicio_nombre}\n"
                f"{duracion_legible(minutos)}"
            )

            with columnas[j]:
                if st.button(
                    etiqueta,
                    key=f"servicio_{i + j}",
                    use_container_width=True,
                    type=(
                        "primary"
                        if seleccionado
                        else "secondary"
                    ),
                ):
                    st.session_state["servicio_demo"] = (
                        servicio_nombre
                    )
                    st.session_state["hora_demo"] = None
                    st.rerun()

    servicio = st.session_state.get("servicio_demo")

    if not servicio:
        return

    duracion = servicios[servicio]

    tecnica = st.selectbox(
        "¿Con quién quieres tu cita?",
        TECNICAS,
        key="tecnica_demo",
    )

    st.markdown(
        f'<div class="selected-state">'
        f'<span class="accent">02</span> &nbsp; '
        f'<b>{texto_seguro(servicio)}</b> · '
        f'{duracion_legible(duracion)} · Elige el día'
        f'</div>',
        unsafe_allow_html=True,
    )

    fecha = st.date_input(
        "Fecha de la cita",
        min_value=date.today(),
        format="DD/MM/YYYY",
        key="fecha_demo",
    )

    fecha_key = str(fecha)

    if st.session_state.get("_ultima_fecha") != fecha_key:
        st.session_state["_ultima_fecha"] = fecha_key
        st.session_state["hora_demo"] = None

    try:
        horas = horarios_disponibles(
            fecha,
            duracion,
            tecnica,
            negocio_id,
        )
    except Exception:
        st.error(
            "No fue posible consultar los horarios disponibles."
        )
        return

    if not horas:
        if fecha.weekday() == 6:
            st.warning("Nailcraft permanece cerrado los domingos.")
        else:
            st.warning(
                "Ese día ya no tiene espacios disponibles. "
                "Prueba otra fecha."
            )
        return

    st.markdown(
        """
        <div class="selected-state">
            <span class="accent">03</span>
            &nbsp; Elige un horario disponible
        </div>
        """,
        unsafe_allow_html=True,
    )

    for i in range(0, len(horas), 3):
        columnas = st.columns(3, gap="small")

        for j, hora_opcion in enumerate(horas[i:i + 3]):
            seleccionado = (
                st.session_state.get("hora_demo")
                == hora_opcion
            )

            with columnas[j]:
                if st.button(
                    f"{'✓ ' if seleccionado else ''}"
                    f"{hora_opcion}",
                    key=f"hora_{i + j}",
                    use_container_width=True,
                    type=(
                        "primary"
                        if seleccionado
                        else "secondary"
                    ),
                ):
                    st.session_state["hora_demo"] = hora_opcion
                    st.rerun()

    hora = st.session_state.get("hora_demo")

    if not hora:
        return

    fecha_legible = fecha.strftime("%d/%m/%Y")

    st.markdown(
        f'<div class="booking-summary">'
        f'<div class="eyebrow">Tu cita</div>'
        f'<strong>{texto_seguro(servicio)}</strong><br>'
        f'<span>{fecha_legible} · '
        f'<span class="accent">{texto_seguro(hora)}</span> · '
        f'{duracion_legible(duracion)} · '
        f'{texto_seguro(tecnica)}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown("### Solo faltan tus datos")

    nombre = st.text_input(
        "Nombre completo",
        placeholder="Tu nombre",
        key="nombre_demo",
    )

    whatsapp = st.text_input(
        "WhatsApp",
        max_chars=10,
        placeholder="10 dígitos",
        key="whatsapp_demo",
    )

    comentarios = st.text_area(
        "Comentarios (opcional)",
        placeholder="¿Hay algo que el negocio deba saber?",
        key="comentarios_demo",
    )

    datos_validos = (
        bool(nombre.strip())
        and whatsapp.isdigit()
        and len(whatsapp) == 10
    )

    if whatsapp and not (
        whatsapp.isdigit() and len(whatsapp) == 10
    ):
        st.caption("Ingresa los 10 números de tu WhatsApp.")

    enviar = st.button(
        "Confirmar mi cita",
        key="agendar_cita",
        use_container_width=True,
        disabled=not datos_validos,
        type="primary",
    )

    if not enviar:
        return

    try:
        if hora not in horarios_disponibles(
            fecha,
            duracion,
            tecnica,
            negocio_id,
        ):
            st.error(
                "Ese horario acaba de ocuparse. "
                "Elige otro disponible."
            )
            st.session_state["hora_demo"] = None
            return

        if negocio_id:
            guardar_cita(
                {
                    "business_id": negocio_id,
                    "giro": giro,
                    "nombre": nombre.strip(),
                    "whatsapp": whatsapp.strip(),
                    "servicio": servicio,
                    "tecnica": tecnica,
                    "duracion": duracion,
                    "fecha": str(fecha),
                    "hora": hora,
                    "estado": "Pendiente",
                    "comentarios": comentarios.strip(),
                    "plan": negocio.get("plan", "Prueba 15 días"),
                }
            )

            mensaje_exito = (
                "¡Listo! Tu cita quedó confirmada."
            )
        else:
            mensaje_exito = (
                "Demostración completada. Para guardar citas "
                "se necesita el enlace de un negocio registrado."
            )

        st.success(mensaje_exito)

        st.markdown(
            f'<div class="booking-summary">'
            f'<div class="eyebrow">Reserva confirmada</div>'
            f'<strong>{texto_seguro(nombre)}</strong><br>'
            f'<span>{texto_seguro(servicio)}</span><br>'
            f'<span>{fecha_legible} · '
            f'<span class="accent">{texto_seguro(hora)}</span>'
            f'</span></div>',
            unsafe_allow_html=True,
        )

    except Exception:
        st.error(
            "No fue posible guardar la cita. "
            "Intenta nuevamente."
        )


def mostrar_planes():
    st.markdown(
        """
        <section class="section">
            <div class="eyebrow">Elige cómo crecer</div>
            <h2>Una agenda que crece con tu negocio</h2>
            <p>
                Empieza simple y activa más herramientas
                cuando las necesites.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    columnas = st.columns(3, gap="small")

    for columna, plan in zip(columnas, PLANES):
        with columna:
            if st.button(
                f"Conoce {plan}",
                key=f"plan_{plan.lower()}",
                use_container_width=True,
            ):
                st.session_state["plan"] = plan

    plan = st.session_state.get("plan")

    if not plan:
        st.info("Elige un plan para conocer sus beneficios.")
        return

    beneficios = "".join(
        f"<li>✓ {texto_seguro(beneficio)}</li>"
        for beneficio in PLANES[plan]
    )

    st.markdown(
        f'<section class="glass-card">'
        f'<div class="eyebrow">{texto_seguro(plan)}</div>'
        f'<h3>Esto es lo que puedes lograr</h3>'
        f'<ul>{beneficios}</ul>'
        f'</section>',
        unsafe_allow_html=True,
    )


def mostrar_agenda_publica():
    negocio_id = str(
        st.query_params.get("business", "")
    ).strip()

    try:
        negocio = (
            obtener_negocio(negocio_id)
            if negocio_id
            else obtener_negocio_publico()
        )
    except Exception:
        negocio = None
        st.error(
            "No fue posible consultar la información "
            "del negocio."
        )

    if negocio_id and not negocio:
        st.warning(
            "El enlace de esta agenda no corresponde "
            "a un negocio activo."
        )

    if negocio and dias_prueba_restantes(negocio) == 0:
        st.warning(
            "La prueba de esta agenda terminó. "
            "Contacta a Nailcraft para reservar por WhatsApp."
        )
        mensaje = quote("Hola, quiero reservar una cita en Nailcraft.")
        st.link_button(
            "Reservar por WhatsApp",
            f"https://wa.me/{WHATSAPP_NEGOCIO}?text={mensaje}",
            use_container_width=True,
        )
        return

    marca = BASE_DIR / "static" / "nailcraft-mark.png"
    cabecera_izquierda, cabecera_derecha = st.columns([4, 1])
    with cabecera_izquierda:
        st.markdown(
            "<h1 style='margin:.35rem 0 0'>Nailcraft</h1>"
            "<p style='margin-top:0'>Nail studio · Ciudad Juárez</p>",
            unsafe_allow_html=True,
        )
    with cabecera_derecha:
        if marca.exists():
            st.image(str(marca), width=72)

    mostrar_experiencia(negocio)

    st.markdown(
        """
        <section class="section">
            <h2>Atención personalizada</h2>
            <p>
                Plaza de las Américas, local E-28 · Ciudad Juárez.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    mensaje = quote(
        "Hola, tengo una pregunta sobre mi cita en Nailcraft."
    )

    st.link_button(
        "Contactar a Nailcraft por WhatsApp",
        f"https://wa.me/{WHATSAPP_NEGOCIO}?text={mensaje}",
        use_container_width=True,
    )

    st.caption(
        "Nailcraft · Tu momento, tus manos, tu estilo."
    )


# =====================================================
# PANEL DEL DUEÑO
# =====================================================

def tarjeta_metrica(valor, etiqueta):
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="value">{texto_seguro(valor)}</div>'
        f'<div class="label">{texto_seguro(etiqueta)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def tarjeta_cita(cita, mostrar_fecha=True):
    inicio = cita.get("inicio")
    fecha_hora = "Fecha sin reconocer"

    if inicio:
        fecha_hora = (
            inicio.strftime("%d/%m/%Y · %I:%M %p")
            if mostrar_fecha
            else inicio.strftime("%I:%M %p")
        )

    estado = cita.get("estado") or "Sin estado"

    st.markdown(
        f'<div class="appointment-card">'
        f'<strong>{texto_seguro(fecha_hora)} · '
        f'{texto_seguro(cita.get("nombre"))}</strong><br>'
        f'<span>{texto_seguro(cita.get("servicio"))}</span><br>'
        f'<span class="meta">'
        f'{texto_seguro(cita.get("giro"))} · '
        f'{texto_seguro(estado)} · '
        f'{texto_seguro(cita.get("whatsapp"))}'
        f'</span></div>',
        unsafe_allow_html=True,
    )


def mostrar_inicio_dueno(citas):
    ahora = datetime.now()
    hoy = ahora.date()

    validas = [
        cita for cita in citas
        if cita.get("inicio")
    ]

    citas_hoy = [
        cita for cita in validas
        if cita["inicio"].date() == hoy
    ]

    proximas = sorted(
        (
            cita for cita in validas
            if cita["inicio"] >= ahora
        ),
        key=lambda cita: cita["inicio"],
    )

    clientes = {
        (
            str(cita.get("whatsapp", "")).strip()
            or str(cita.get("nombre", "")).strip().lower()
        )
        for cita in citas
        if (
            str(cita.get("whatsapp", "")).strip()
            or str(cita.get("nombre", "")).strip()
        )
    }

    izquierda, derecha = st.columns(2, gap="small")

    with izquierda:
        tarjeta_metrica(len(citas_hoy), "Citas hoy")

    with derecha:
        tarjeta_metrica(len(clientes), "Clientes")

    st.markdown("### Próximas citas")

    if not proximas:
        st.info("No hay próximas citas registradas.")
        return

    for cita in proximas[:8]:
        tarjeta_cita(cita)


def mostrar_agenda_dueno(citas):
    st.markdown("### Agenda")

    fecha_filtro = st.date_input(
        "Ver día",
        value=date.today(),
        format="DD/MM/YYYY",
        key="fecha_agenda_dueno",
    )

    del_dia = sorted(
        (
            cita for cita in citas
            if cita.get("inicio")
            and cita["inicio"].date() == fecha_filtro
        ),
        key=lambda cita: cita["inicio"],
    )

    if not del_dia:
        st.info("No hay citas para este día.")
        return

    for cita in del_dia:
        tarjeta_cita(cita, mostrar_fecha=False)


def mostrar_clientes_dueno(citas):
    st.markdown("### Clientes")
    clientes = {}

    for cita in citas:
        whatsapp = str(cita.get("whatsapp", "")).strip()
        nombre = str(cita.get("nombre", "")).strip()
        clave = whatsapp or nombre.lower()

        if not clave:
            continue

        cliente = clientes.setdefault(
            clave,
            {
                "nombre": nombre,
                "whatsapp": whatsapp,
                "citas": 0,
                "ultima": None,
            },
        )

        cliente["citas"] += 1

        if cita.get("inicio") and (
            cliente["ultima"] is None
            or cita["inicio"] > cliente["ultima"]
        ):
            cliente["ultima"] = cita["inicio"]

    if not clientes:
        st.info("Aún no hay clientes registrados.")
        return

    busqueda = st.text_input(
        "Buscar cliente",
        placeholder="Nombre o WhatsApp",
        key="buscar_cliente_dueno",
    ).strip().lower()

    lista = sorted(
        clientes.values(),
        key=lambda cliente: cliente["nombre"].lower(),
    )

    if busqueda:
        lista = [
            cliente for cliente in lista
            if busqueda in cliente["nombre"].lower()
            or busqueda in cliente["whatsapp"].lower()
        ]

    if not lista:
        st.info("No encontramos clientes con esa búsqueda.")
        return

    for cliente in lista:
        ultima = (
            cliente["ultima"].strftime("%d/%m/%Y")
            if cliente["ultima"]
            else "Sin fecha válida"
        )

        st.markdown(
            f'<div class="appointment-card">'
            f'<strong>{texto_seguro(cliente["nombre"])}</strong>'
            f'<br><span>{texto_seguro(cliente["whatsapp"])}</span>'
            f'<br><span class="meta">'
            f'{cliente["citas"]} cita(s) · '
            f'Última: {texto_seguro(ultima)}'
            f'</span></div>',
            unsafe_allow_html=True,
        )


def mostrar_ventas_dueno(citas):
    st.markdown("### Ventas")

    st.info(
        "Nailcraft todavía no guarda precios. "
        "Esta sección muestra actividad de reservaciones."
    )

    hoy = date.today()
    mes_actual = (hoy.year, hoy.month)

    citas_mes = [
        cita for cita in citas
        if cita.get("inicio")
        and (
            cita["inicio"].year,
            cita["inicio"].month,
        ) == mes_actual
    ]

    completadas = [
        cita for cita in citas_mes
        if str(cita.get("estado", "")).strip().lower()
        in {"completada", "completado", "atendida"}
    ]

    izquierda, derecha = st.columns(2, gap="small")

    with izquierda:
        tarjeta_metrica(
            len(citas_mes),
            "Reservas este mes",
        )

    with derecha:
        tarjeta_metrica(
            len(completadas),
            "Completadas",
        )

    conteo_servicios = {}

    for cita in citas_mes:
        servicio = (
            str(cita.get("servicio", "")).strip()
            or "Sin servicio"
        )
        conteo_servicios[servicio] = (
            conteo_servicios.get(servicio, 0) + 1
        )

    st.markdown("### Servicios reservados")

    if not conteo_servicios:
        st.caption("Aún no hay reservaciones este mes.")
        return

    for servicio, cantidad in sorted(
        conteo_servicios.items(),
        key=lambda elemento: (-elemento[1], elemento[0]),
    ):
        st.markdown(
            f"- **{texto_seguro(servicio)}:** {cantidad}"
        )


def mostrar_registro_negocio():
    usuario = datos_usuario()
    nombre_google = str(usuario.get("name", "")).strip()

    st.markdown(
        """
        <section class="owner-header">
            <div class="eyebrow">Primer acceso</div>
            <h1>Configura tu negocio</h1>
            <p>
                Tu cuenta ya fue validada por Google.
                Completa estos datos una sola vez.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    with st.form("registro_negocio"):
        nombre = st.text_input(
            "Nombre del negocio",
            value="Nailcraft",
            placeholder="Nombre comercial",
        )

        celular = st.text_input(
            "WhatsApp del negocio",
            placeholder="10 dígitos",
            max_chars=10,
        )

        registrar = st.form_submit_button(
            "Crear mi espacio privado",
            use_container_width=True,
            type="primary",
        )

    if not registrar:
        return

    if not nombre.strip():
        st.error("Escribe el nombre del negocio.")
        return

    if not (celular.isdigit() and len(celular) == 10):
        st.error("Ingresa un WhatsApp válido de 10 dígitos.")
        return

    try:
        crear_negocio(nombre, celular)
        st.success("Tu espacio privado fue creado.")
        st.rerun()
    except Exception:
        st.error(
            "No fue posible crear el negocio. "
            "Intenta nuevamente."
        )


def mostrar_login_dueno():
    st.markdown(
        """
        <section class="owner-header">
            <div class="eyebrow">Área privada</div>
            <h1>Nailcraft</h1>
            <p>
                Acceso privado mediante tu cuenta de Google.
                Nailcraft no conoce ni almacena tu contraseña.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if st.button(
        "Continuar con Google",
        use_container_width=True,
        type="primary",
        key="login_google",
    ):
        st.login()

    st.caption(
        "Google administra de forma privada tus credenciales."
    )


def cerrar_sesion_dueno():
    st.logout()


def mostrar_panel_dueno():
    if not st.user.is_logged_in:
        mostrar_login_dueno()
        return

    if not usuario_es_dueno():
        st.error(
            "Esta cuenta de Google no está autorizada "
            "para administrar Nailcraft."
        )
        if st.button("Cerrar sesión", use_container_width=True):
            cerrar_sesion_dueno()
        return

    try:
        negocio = obtener_negocio_del_dueno()
    except Exception:
        st.error(
            "No fue posible conectar con Firebase. "
            "Revisa la configuración e intenta nuevamente."
        )
        return

    if not negocio:
        mostrar_registro_negocio()
        return

    nombre_negocio = (
        negocio.get("business_name") or "Mi negocio"
    )

    st.markdown(
        f'<section class="owner-header">'
        f'<div class="eyebrow">Panel del negocio</div>'
        f'<h1>{texto_seguro(nombre_negocio)}</h1>'
        f'<p>Las reservaciones de tu agenda, '
        f'en un solo lugar.</p>'
        f'</section>',
        unsafe_allow_html=True,
    )

    dias = dias_prueba_restantes(negocio)
    if dias:
        st.info(f"Prueba gratuita: quedan {dias} día(s).")
    else:
        st.warning(
            "La prueba gratuita terminó. Puedes consultar las citas "
            "existentes, pero la agenda pública ya no acepta reservas."
        )

    enlace_publico = APP_URL

    st.markdown("### Enlace de tu agenda")

    st.code(enlace_publico, language=None)

    st.link_button(
        "Abrir mi agenda pública",
        enlace_publico,
        use_container_width=True,
    )

    if st.button(
        "Cerrar sesión",
        use_container_width=True,
        key="cerrar_sesion_dueno",
    ):
        cerrar_sesion_dueno()

    try:
        citas = obtener_citas(negocio["id"])
    except Exception:
        st.error(
            "No fue posible leer las citas de Firestore. "
            "Intenta nuevamente."
        )
        return

    seccion = st.radio(
        "Sección del panel",
        ["Inicio", "Agenda", "Clientes", "Ventas"],
        horizontal=True,
        label_visibility="collapsed",
        key="seccion_dueno",
    )

    if seccion == "Inicio":
        mostrar_inicio_dueno(citas)
    elif seccion == "Agenda":
        mostrar_agenda_dueno(citas)
    elif seccion == "Clientes":
        mostrar_clientes_dueno(citas)
    else:
        mostrar_ventas_dueno(citas)


# =====================================================
# NAVEGACIÓN PRINCIPAL
# =====================================================

def main():
    aplicar_estilos()

    st.session_state.setdefault("plan", None)
    st.session_state.setdefault("vista_app", "publica")

    if st.query_params.get("business"):
        st.session_state["vista_app"] = "publica"
    elif (
        st.user.is_logged_in
        and not st.session_state.get("_login_detectado")
    ):
        st.session_state["_login_detectado"] = True
        st.session_state["vista_app"] = "dueno"

    vista = st.session_state["vista_app"]

    if vista == "publica":
        izquierda, derecha = st.columns([2.2, 1.4])

        with derecha:
            if st.button(
                "Acceso propietarios",
                key="acceso_propietarios",
                use_container_width=True,
            ):
                st.query_params.clear()
                st.session_state["vista_app"] = "login"
                st.rerun()

        mostrar_agenda_publica()

    elif vista == "login":
        if st.user.is_logged_in:
            st.session_state["vista_app"] = "dueno"
            st.rerun()

        if st.button(
            "← Volver a la agenda",
            key="volver_agenda",
        ):
            st.session_state["vista_app"] = "publica"
            st.rerun()

        mostrar_login_dueno()

    elif vista == "dueno":
        mostrar_panel_dueno()

    else:
        st.session_state["vista_app"] = "publica"
        st.rerun()


if __name__ == "__main__":
    main()
