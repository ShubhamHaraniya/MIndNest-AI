"""Which uploads are accepted, shared by the API (at upload) and the worker (before parsing).

The extension decides the type, never the client-supplied Content-Type, and the first bytes
must agree with it, so a renamed executable is rejected.
"""

ALLOWED_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def looks_like(extension: str, head: bytes) -> bool:
    """True when the leading bytes are plausible for the extension."""
    if extension == "pdf":
        return b"%PDF-" in head[:1024]
    if extension in {"pptx", "docx"}:
        return head.startswith(b"PK\x03\x04")
    if extension == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {"jpg", "jpeg"}:
        return head.startswith(b"\xff\xd8\xff")
    if extension == "webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if extension in {"txt", "md"}:
        return b"\x00" not in head[:4096]
    return False
