from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import firebase_admin
import streamlit as st
from firebase_admin import credentials, firestore


def service_account_config(
    value: str | dict[str, Any],
) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "El secreto service_account_json no contiene JSON válido."
            ) from exc

        if isinstance(parsed, dict):
            return parsed

    raise ValueError(
        "El secreto service_account_json debe ser un objeto JSON válido."
    )


@lru_cache(maxsize=1)
def init_firebase():
    if "firebase" not in st.secrets:
        raise RuntimeError(
            "Falta la sección [firebase] en los secretos de Streamlit."
        )

    config = st.secrets["firebase"]

    if not firebase_admin._apps:
        service_account_json = config.get(
            "service_account_json"
        )
        service_account_file = config.get(
            "service_account_file"
        )

        if service_account_json:
            certificate_data = service_account_config(
                service_account_json
            )
            credential = credentials.Certificate(
                certificate_data
            )
        elif service_account_file:
            credential = credentials.Certificate(
                service_account_file
            )
        else:
            raise RuntimeError(
                "Configura service_account_json o "
                "service_account_file en los secretos de Streamlit."
            )

        project_id = config.get("project_id")

        if not project_id:
            raise RuntimeError(
                "Falta project_id en los secretos de Firebase."
            )

        firebase_admin.initialize_app(
            credential,
            {
                "projectId": project_id,
            },
        )

    return firestore.client()


def db():
    return init_firebase()
