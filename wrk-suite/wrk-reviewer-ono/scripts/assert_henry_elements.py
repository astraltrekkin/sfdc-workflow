#!/usr/bin/env python3
"""Assert Henry collage elements are present and inline-table in an Ono email HTML.

Fails (exit 1) if the HTML is not ready to send. On success, prints a receipt
for the chat reply.

Usage:
  python3 scripts/assert_henry_elements.py /path/to/filled-email.html

When rewriting Henry collage img src to data-URI/https/CID, set:
  data-henry-element="<relpath under henry/elements>"
e.g. data-henry-element="ink/ink-figure.png"

Commenter profile avatar (required, exactly one) must use:
  data-ono-avatar="1"
and a inline-table src (resized data-URI or https). Do NOT set data-henry-element
on the avatar.

Exit codes:
  0 — inline-table kit elements present (+ required avatar)
  1 — validation failed
  2 — usage / IO error

Stdout on success:
  ONO_HENRY_ELEMENTS_OK=1
  ELEMENTS_USED: atmospheres/glow-blue.png, ...
  ONO_HENRY_ELEMENTS_JSON={...}
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------

HENRY_ELEMENTS = Path.home() / ".claude" / "skills" / "henry" / "elements"
# Fixed count in ~/.claude/skills/henry/templates/email-dark.html
EXPECTED_HENRY_IMG_COUNT = 10
# Required commenter avatar imgs tagged data-ono-avatar="1"
EXPECTED_AVATAR_IMG_COUNT = 1
MIN_DATA_URI_BYTES = 512
MIN_AVATAR_DATA_URI_BYTES = 200

IMG_RE = re.compile(r"<img\b([^>]*)>", re.IGNORECASE)
ATTR_RE = re.compile(
    r"""([^\s=]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
    re.IGNORECASE,
)
SAFE_SRC_RE = re.compile(r"^(data:image/|https://|cid:)", re.IGNORECASE)
DATA_URI_RE = re.compile(
    r"^data:image/([a-z0-9+.-]+);base64,(.+)$",
    re.IGNORECASE | re.DOTALL,
)


def parse_attrs(attr_blob: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in ATTR_RE.finditer(attr_blob):
        key = m.group(1).lower()
        val = (
            m.group(2)
            if m.group(2) is not None
            else (m.group(3) if m.group(3) is not None else m.group(4) or "")
        )
        out[key] = val
    return out


def load_kit_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    if not HENRY_ELEMENTS.is_dir():
        return hashes
    for path in HENRY_ELEMENTS.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            continue
        rel = path.relative_to(HENRY_ELEMENTS).as_posix()
        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def decode_data_uri(src: str) -> bytes | None:
    m = DATA_URI_RE.match(src.strip())
    if not m:
        return None
    try:
        return base64.b64decode(m.group(2), validate=False)
    except Exception:
        return None


def element_from_relative_src(src: str) -> str | None:
    norm = src.replace("\\", "/")
    key = "elements/"
    idx = norm.find(key)
    if idx == -1:
        return None
    return norm[idx + len(key) :].split("?")[0]


def is_relative_elements_src(src: str) -> bool:
    return (
        src.startswith("../elements/")
        or src.startswith("./elements/")
        or src.startswith("elements/")
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in {"-h", "--help"}:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    html_path = Path(argv[1]).expanduser().resolve()
    if not html_path.is_file():
        print(f"error: file not found: {html_path}", file=sys.stderr)
        return 2

    html = html_path.read_text(encoding="utf-8", errors="replace")
    imgs = list(IMG_RE.finditer(html))
    errors: list[str] = []
    elements_used: list[str] = []
    kit_hash_matched: list[str] = []
    relative_left: list[str] = []
    henry_imgs = 0
    avatar_imgs = 0

    kit = load_kit_hashes()
    hash_to_rel = {h: rel for rel, h in kit.items()}

    if not kit:
        errors.append(f"Henry elements kit missing or empty: {HENRY_ELEMENTS}")

    for i, match in enumerate(imgs, start=1):
        attrs = parse_attrs(match.group(1))
        src = (attrs.get("src") or "").strip()
        tagged = (attrs.get("data-henry-element") or "").strip().lstrip("/")
        is_avatar = (attrs.get("data-ono-avatar") or "").strip() in {
            "1",
            "true",
            "yes",
        }

        if not src:
            errors.append(f"img[{i}]: missing src")
            continue

        if is_avatar:
            avatar_imgs += 1
            if tagged:
                errors.append(
                    f"img[{i}]: avatar must not set data-henry-element "
                    "(use data-ono-avatar only)"
                )
            if is_relative_elements_src(src):
                relative_left.append(src)
                errors.append(f"img[{i}]: avatar has relative elements src: {src}")
                continue
            if not SAFE_SRC_RE.match(src):
                errors.append(f"img[{i}]: avatar src not inline-table: {src[:96]}")
                continue
            raw = decode_data_uri(src)
            if raw is not None and len(raw) < MIN_AVATAR_DATA_URI_BYTES:
                errors.append(
                    f"img[{i}]: avatar data-URI too small ({len(raw)} bytes)"
                )
            continue

        # Henry collage / stage imgs
        henry_imgs += 1
        identified: str | None = None

        if is_relative_elements_src(src):
            relative_left.append(src)
            identified = element_from_relative_src(src)
            if identified:
                elements_used.append(identified)
            errors.append(f"img[{i}]: relative elements src still present: {src}")
            continue

        if not SAFE_SRC_RE.match(src):
            errors.append(f"img[{i}]: src not inline-table: {src[:96]}")
            continue

        raw = decode_data_uri(src)
        if raw is not None:
            if len(raw) < MIN_DATA_URI_BYTES:
                errors.append(
                    f"img[{i}]: data-URI too small ({len(raw)} bytes) — placeholder?"
                )
            digest = hashlib.sha256(raw).hexdigest()
            by_hash = hash_to_rel.get(digest)
            if by_hash:
                identified = by_hash
                kit_hash_matched.append(by_hash)

        if tagged:
            if kit and tagged not in kit:
                errors.append(
                    f"img[{i}]: data-henry-element not in Henry kit: {tagged}"
                )
            else:
                identified = tagged

        if not identified:
            errors.append(
                f"img[{i}]: cannot identify Henry element — set "
                'data-henry-element="genre/file.png" when rewriting src '
                '(or data-ono-avatar="1" for the commenter profile)'
            )
        else:
            elements_used.append(identified)

    if henry_imgs != EXPECTED_HENRY_IMG_COUNT:
        errors.append(
            f"Henry img count {henry_imgs} != expected {EXPECTED_HENRY_IMG_COUNT} "
            "(Henry email-dark template)"
        )
    if avatar_imgs != EXPECTED_AVATAR_IMG_COUNT:
        errors.append(
            f"avatar img count {avatar_imgs} != expected "
            f'{EXPECTED_AVATAR_IMG_COUNT} (tag exactly one <img data-ono-avatar="1">)'
        )

    # Deduplicate preserving order
    uniq_elements = list(dict.fromkeys(elements_used))

    ok = (
        not errors
        and henry_imgs == EXPECTED_HENRY_IMG_COUNT
        and avatar_imgs == EXPECTED_AVATAR_IMG_COUNT
        and len(uniq_elements) >= 1
    )

    receipt = {
        "ok": ok,
        "img_count": len(imgs),
        "henry_img_count": henry_imgs,
        "avatar_img_count": avatar_imgs,
        "expected_henry_img_count": EXPECTED_HENRY_IMG_COUNT,
        "expected_avatar_img_count": EXPECTED_AVATAR_IMG_COUNT,
        # keep legacy key for older hook consumers
        "expected_img_count": EXPECTED_HENRY_IMG_COUNT,
        "elements": uniq_elements,
        "kit_hash_matched": list(dict.fromkeys(kit_hash_matched)),
        "relative_left": relative_left,
        "errors": errors,
        "henry_elements_dir": str(HENRY_ELEMENTS),
        "html_path": str(html_path),
    }
    elements_line = ", ".join(uniq_elements) if uniq_elements else "(none)"
    json_line = json.dumps(receipt, separators=(",", ":"))

    if ok:
        print("ONO_HENRY_ELEMENTS_OK=1")
        print(f"ELEMENTS_USED: {elements_line}")
        print(f"ONO_HENRY_ELEMENTS_JSON={json_line}")
        return 0

    print("ONO_HENRY_ELEMENTS_OK=0", file=sys.stderr)
    print(f"ELEMENTS_USED: {elements_line}", file=sys.stderr)
    for err in errors:
        print(f"error: {err}", file=sys.stderr)
    print(f"ONO_HENRY_ELEMENTS_JSON={json_line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
