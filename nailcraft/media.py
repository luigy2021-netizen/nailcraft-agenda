from __future__ import annotations

import base64
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 300_000

CATEGORY_SIZES = {
    "staff": (700, 700),
    "collage": (1800, 900),
}

QUALITY_LEVELS = (82, 76, 70, 64, 58, 50, 42)


def encode_webp(
    image: Image.Image,
    quality: int,
) -> bytes:
    output = io.BytesIO()
    image.save(
        output,
        format="WEBP",
        quality=quality,
        method=6,
    )
    return output.getvalue()


def upload_image(
    salon_id: str,
    category: str,
    uploaded_file,
) -> dict[str, str]:
    """Optimiza una imagen y la devuelve como data URL.

    Las fotografías de colaboradoras se limitan a 700 × 700 px.
    Los collages conservan hasta 1800 × 900 px. Cada imagen queda
    por debajo de 300 KiB antes de convertirla a Base64.
    """
    del salon_id

    if category not in CATEGORY_SIZES:
        raise ValueError("INVALID_IMAGE_CATEGORY")

    try:
        image = Image.open(uploaded_file)
        image.load()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise ValueError("INVALID_IMAGE") from exc

    image = ImageOps.exif_transpose(image).convert("RGB")

    max_width, max_height = CATEGORY_SIZES[category]
    image.thumbnail(
        (max_width, max_height),
        Image.Resampling.LANCZOS,
    )

    encoded = b""

    for quality in QUALITY_LEVELS:
        encoded = encode_webp(image, quality)

        if len(encoded) <= MAX_IMAGE_BYTES:
            break

    resize_attempts = 0

    while (
        len(encoded) > MAX_IMAGE_BYTES
        and resize_attempts < 5
    ):
        new_width = max(1, int(image.width * 0.85))
        new_height = max(1, int(image.height * 0.85))

        image = image.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS,
        )
        encoded = encode_webp(image, quality=42)
        resize_attempts += 1

    if len(encoded) > MAX_IMAGE_BYTES:
        raise ValueError("IMAGE_TOO_LARGE")

    data_url = (
        "data:image/webp;base64,"
        + base64.b64encode(encoded).decode("ascii")
    )

    return {
        "url": data_url,
        "storage_path": "",
        "storage": "firestore-inline",
    }


def delete_image(path: str | None) -> None:
    """No requiere borrar archivos externos.

    La imagen se almacena dentro del documento de Firestore y desaparece
    cuando el campo o documento correspondiente se elimina.
    """
    del path
    return None
