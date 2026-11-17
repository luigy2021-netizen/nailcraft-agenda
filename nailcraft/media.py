
from __future__ import annotations

from datetime import date, datetime

import streamlit as st


# ==========================================
# CONFIGURACIÓN GENERAL
# ==========================================

st.set_page_config(
    page_title="Kroniq | Agenda Digital",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ==========================================
# ESTILOS
# ==========================================

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 2rem;
        max-width: 1200px;
    }

    h1, h2, h3 {
        color: #263238;
    }

    .stButton > button {
        border-radius: 8px;
    }

    .kroniq-footer {
        text-align: center;
        color: #777;
        font-size: 13px;
        padding-top: 30px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ==========================================
# ESTADO DE LA APLICACIÓN
# ==========================================

if "kroniq_initialized" not in st.session_state:
    st.session_state.kroniq_initialized = True

if "salon_name" not in st.session_state:
    st.session_state.salon_name = "Nail Craft"

if "appointments" not in st.session_state:
    st.session_state.appointments = []


# ==========================================
# ENCABEZADO
# ==========================================

st.title("📅 KRONIQ")
st.caption("Sistema inteligente de agendas digitales")

st.divider()


# ==========================================
# MENÚ PRINCIPAL
# ==========================================

with st.sidebar:
    st.title("KRONIQ")
    st.caption("Panel de demostración")

    page = st.radio(
        "Navegación",
        [
            "Inicio",
            "Agenda",
            "Colaboradoras",
            "Servicios",
            "Configuración",
        ],
    )

    st.divider()
    st.success("Sistema iniciado correctamente")


# ==========================================
# PÁGINA DE INICIO
# ==========================================

if page == "Inicio":

    st.header(
        f"Bienvenido a {st.session_state.salon_name}"
    )

    st.write(
        "Esta es la primera versión funcional "
        "de la nueva plataforma Kroniq."
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Escritorios disponibles",
            5,
        )

    with col2:
        st.metric(
            "Citas registradas",
            len(st.session_state.appointments),
        )

    with col3:
        st.metric(
            "Estado del sistema",
            "Activo",
        )

    st.success(
        "Kroniq se está ejecutando correctamente."
    )


# ==========================================
# AGENDA
# ==========================================

elif page == "Agenda":

    st.header("Agenda de citas")

    selected_date = st.date_input(
        "Selecciona una fecha",
        value=date.today(),
    )

    st.info(
        "La agenda está preparada para incorporar "
        "las reservaciones y horarios."
    )

    st.write(
        "Fecha seleccionada:",
        selected_date.strftime("%d/%m/%Y"),
    )

    if st.session_state.appointments:
        st.dataframe(
            st.session_state.appointments,
            use_container_width=True,
        )
    else:
        st.write("Todavía no hay citas registradas.")


# ==========================================
# COLABORADORAS
# ==========================================

elif page == "Colaboradoras":

    st.header("Colaboradoras")

    st.write(
        "Kroniq permitirá administrar hasta "
        "cinco escritorios por salón."
    )

    for number in range(1, 6):
        with st.expander(
            f"Escritorio {number}"
        ):
            st.write(
                "Pendiente de configurar colaboradora, "
                "servicios y horarios."
            )


# ==========================================
# SERVICIOS
# ==========================================

elif page == "Servicios":

    st.header("Catálogo de servicios")

    st.info(
        "Aquí configuraremos los servicios, "
        "precios y duración de cada tratamiento."
    )


# ==========================================
# CONFIGURACIÓN
# ==========================================

elif page == "Configuración":

    st.header("Configuración del salón")

    with st.form("salon_settings"):

        salon_name = st.text_input(
            "Nombre del salón",
            value=st.session_state.salon_name,
        )

        save = st.form_submit_button(
            "Guardar configuración",
            type="primary",
        )

    if save:

        if salon_name.strip():

            st.session_state.salon_name = (
                salon_name.strip()
            )

            st.success(
                "Configuración guardada "
                "durante esta sesión."
            )

            st.rerun()

        else:
            st.error(
                "El nombre del salón no puede estar vacío."
            )


# ==========================================
# PIE DE PÁGINA
# ==========================================

st.divider()

st.markdown(
    """
    <div class="kroniq-footer">
        KRONIQ · Agenda Digital
        <br>
        Versión inicial de reconstrucción
    </div>
    """,
    unsafe_allow_html=True,
)
