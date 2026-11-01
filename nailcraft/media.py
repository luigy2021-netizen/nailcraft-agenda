from __future__ import annotations

import uuid

from PIL import Image

from .firebase import bucket


def upload_image(salon_id: str, category: str, uploaded_file) -> dict[str, str]:
    image = Image.open(uploaded_file)
    image.verify()
    uploaded_file.seek(0)
    ext = (getattr(uploaded_file, "name", "image.jpg").rsplit(".", 1)[-1] or "jpg").lower()
    if ext not in {"jpg", "jpeg", "png", "webp"}:
        raise ValueError("FORMAT")
    path = f"salons/{salon_id}/{category}/{uuid.uuid4().hex}.{ext}"
    blob = bucket().blob(path)
    blob.upload_from_file(uploaded_file, content_type=getattr(uploaded_file, "type", "image/jpeg"))
    blob.make_public()
    return {"url": blob.public_url, "storage_path": path}


def delete_image(path: str | None) -> None:
    if path:
        bucket().blob(path).delete()

