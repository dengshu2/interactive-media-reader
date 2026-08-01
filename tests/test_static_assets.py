from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class IdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        identifier = dict(attrs).get("id")
        if identifier:
            self.ids.append(identifier)


class StaticAssetTests(unittest.TestCase):
    def test_html_ids_are_unique(self):
        parser = IdParser()
        parser.feed((ROOT / "assets" / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertTrue({"media", "audioFallback", "reader", "player"}.issubset(parser.ids))

    def test_frontend_has_no_remote_dependencies(self):
        combined = "\n".join(
            (ROOT / "assets" / name).read_text(encoding="utf-8")
            for name in ("index.html", "styles.css", "app.js")
        )
        # The SVG XML namespace is an identifier, not a fetched resource.
        combined = combined.replace("http://www.w3.org/2000/svg", "")
        self.assertNotIn("fonts.googleapis.com", combined)
        self.assertNotIn("https://", combined)
        self.assertNotIn("http://", combined)

    def test_frontend_uses_text_content_for_transcript(self):
        script = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn("span.textContent = sentence.text", script)


if __name__ == "__main__":
    unittest.main()
