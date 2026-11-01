from __future__ import annotations

import json
from functools import lru_cache

import firebase_admin
import streamlit as st
from firebase_admin import credentials, firestore, storage


@lru_cache(maxsize=1)
def init_firebase():
    cfg = st.secrets["firebase"]
    if not firebase_admin._apps:
        if cfg.get("service_account_json"):
            cred = credentials.Certificate(json.loads(cfg["service_account_json"]))
        else:
            cred = credentials.Certificate(cfg["service_account_file"])
        firebase_admin.initialize_app(
            cred,
            {"projectId": cfg["project_id"], "storageBucket": cfg["storage_bucket"]},
        )
    return firestore.client(), storage.bucket()


def db():
    return init_firebase()[0]


def bucket():
    return init_firebase()[1]

