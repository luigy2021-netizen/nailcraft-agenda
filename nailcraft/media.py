from __future__ import annotations

import base64
import io

from PIL import Image, ImageOps


def upload_image(salon_id: str, category: str, uploaded_file) -> dict[str, str]:
    """Optimiza una imagen y la devuelve como data URL para Firestore.

    Cada imagen queda por debajo de 300 KiB antes de Base64, lo que mantiene
    el documento por debajo del límite de 1 MiB de Firestore.
    """
    image = Image.open(uploaded_file)
    image = ImageOps.exif_transpose(image).convert("RGB")
    max_side = 700 if category == "staff" else 1200
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    encoded = b""
    for quality in (78, 68, 58, 48, 38):
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=quality, method=6)
        encoded = output.getvalue()
        if len(encoded) <= 300_000:
            break
    if len(encoded) > 300_000:
        image.thumbnail((800, 800), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=40, method=6)
        encoded = output.getvalue()
    if len(encoded) > 300_000:
        raise ValueError("IMAGE_TOO_LARGE")

    data_url = "data:image/webp;base64," + base64.b64encode(encoded).decode("ascii")
    return {"url": data_url, "storage_path": "", "storage": "firestore-inline"}


def delete_image(path: str | None) -> None:
    # La imagen está dentro del propio documento; al borrarlo no queda archivo.
    return None

