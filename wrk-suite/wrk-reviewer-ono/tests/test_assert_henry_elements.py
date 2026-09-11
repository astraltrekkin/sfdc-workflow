#!/usr/bin/env python3
"""Tests for assert_henry_elements.py (negative + positive controls)."""

from __future__ import annotations

import base64
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "assert_henry_elements.py"
)
TEMPLATE = (
    Path.home()
    / ".claude"
    / "skills"
    / "henry"
    / "templates"
    / "email-dark.html"
)
KIT = Path.home() / ".claude" / "skills" / "henry" / "elements"
TEMPLATE_PATHS = [
    "atmospheres/glow-blue.png",
    "textures/halftone-lime-arc.png",
    "ink/ink-figure.png",
    "objects/butterfly-cutout.png",
    "atmospheres/glow-blue.png",
    "ink/ink-figure.png",
    "objects/butterfly-cutout.png",
    "objects/butterfly-cutout.png",
    "ink/ink-face-blue.png",
    "atmospheres/holo-heart.png",
]


def run_assert(html_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(html_path)],
        capture_output=True,
        text=True,
    )


def henry_imgs_html() -> list[str]:
    imgs = []
    for rel in TEMPLATE_PATHS:
        raw = (KIT / rel).read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        imgs.append(
            f'<img src="data:image/png;base64,{b64}" '
            f'data-henry-element="{rel}" />'
        )
    return imgs


def avatar_img_html() -> str:
    # >= MIN_AVATAR_DATA_URI_BYTES
    raw = b"a" * 220
    b64 = base64.b64encode(raw).decode("ascii")
    return (
        f'<img data-ono-avatar="1" '
        f'src="data:image/png;base64,{b64}" width="72" alt="@tester" />'
    )


class AssertHenryElementsTests(unittest.TestCase):
    def test_raw_template_fails(self) -> None:
        """Negative control: relative ../elements/ paths must fail."""
        result = run_assert(TEMPLATE)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("ONO_HENRY_ELEMENTS_OK=0", result.stderr)

    def test_tagged_data_uris_with_avatar_pass(self) -> None:
        html = (
            "<html><body>"
            + "\n".join(henry_imgs_html())
            + "\n"
            + avatar_img_html()
            + "</body></html>"
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".html", delete=False
        ) as fh:
            fh.write(html)
            path = Path(fh.name)
        try:
            result = run_assert(path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ONO_HENRY_ELEMENTS_OK=1", result.stdout)
            self.assertIn("ELEMENTS_USED:", result.stdout)
            self.assertIn("ink/ink-figure.png", result.stdout)
        finally:
            path.unlink(missing_ok=True)

    def test_henry_only_without_avatar_fails(self) -> None:
        html = "<html><body>" + "\n".join(henry_imgs_html()) + "</body></html>"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".html", delete=False
        ) as fh:
            fh.write(html)
            path = Path(fh.name)
        try:
            result = run_assert(path)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("avatar img count", result.stderr)
        finally:
            path.unlink(missing_ok=True)

    def test_tiny_placeholders_fail(self) -> None:
        tiny = base64.b64encode(b"x" * 20).decode("ascii")
        imgs = [f'<img src="data:image/png;base64,{tiny}" />' for _ in range(10)]
        html = "<html><body>" + "".join(imgs) + avatar_img_html() + "</body></html>"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".html", delete=False
        ) as fh:
            fh.write(html)
            path = Path(fh.name)
        try:
            result = run_assert(path)
            self.assertEqual(result.returncode, 1, result.stdout)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
