"""Keep the editable catalogue and generated exports consistent."""
import json
import ast
import subprocess
import sys
from pathlib import Path
from html.parser import HTMLParser
import re

ROOT = Path(__file__).resolve().parents[1]


def test_generated_localization_exports_are_current():
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_i18n.py"), "--check"], check=True)


def test_all_keyed_template_copy_has_a_portuguese_translation():
    import re
    catalogue = json.loads((ROOT / "static" / "pt-PT.json").read_text())
    for path in (ROOT / "templates").glob("*.html"):
        for key in re.findall(r'data-i18n(?:-(?:title|placeholder|aria-label|alt|confirm|data-label))?="([^"\n]+)"', path.read_text()):
            # Jinja-generated error keys are resolved at runtime.
            if "{{" not in key:
                assert key in catalogue, f"Missing translation for {key!r} in {path.name}"


def test_user_facing_domain_errors_have_portuguese_translations():
    catalogue = json.loads((ROOT / "static" / "pt-PT.json").read_text())
    for filename in ("main.py", "database.py", "game_logic.py", "league_auctions.py", "league_scoring.py", "web_security.py"):
        for node in ast.walk(ast.parse((ROOT / filename).read_text())):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in ("ValueError", "HTTPException", "flash"):
                continue
            if filename == "web_security.py" and node.func.id != "HTTPException":
                continue  # Middleware configuration errors are developer diagnostics.
            values = node.args[1:] if node.func.id == "HTTPException" else node.args
            for value in values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and len(value.value) > 7:
                    assert value.value in catalogue, f"Untranslated user-facing message at {filename}:{node.lineno}: {value.value}"


def test_legacy_static_interface_copy_has_catalogue_coverage():
    """Cover remaining interface labels while old templates migrate to keys."""
    catalogue = json.loads((ROOT / "static" / "pt-PT.json").read_text())
    unchanged = {"Liga", "SX-AAC", "Liga SX-AAC", "CR"}

    class InterfaceCopy(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.missing = set()

        def inspect(self, text):
            for piece in text.split("__JINJA__"):
                piece = piece.strip()
                if not re.search("[A-Za-z]", piece) or "{{" in piece:
                    continue
                if piece not in catalogue and piece not in unchanged:
                    self.missing.add(piece)

        def handle_starttag(self, tag, attributes):
            attributes = dict(attributes)
            skip = bool(self.stack and self.stack[-1][1]) or tag in (
                "script", "style", "noscript", "textarea", "svg", "code", "pre"
            ) or "data-no-i18n" in attributes or "data-i18n" in attributes
            if tag not in ("img", "input", "br", "hr", "meta", "link", "source", "wbr"):
                self.stack.append((tag, skip))
            if not skip:
                for attribute in ("title", "aria-label", "alt", "placeholder", "data-confirm", "data-label"):
                    if attribute in attributes:
                        self.inspect(attributes[attribute])

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

        def handle_data(self, text):
            if not self.stack or not self.stack[-1][1]:
                self.inspect(text)

    for path in (ROOT / "templates").glob("*.html"):
        source = path.read_text()
        parser = InterfaceCopy()
        parser.feed(re.sub(r"{%.*?%}", "__JINJA__", source, flags=re.S))
        assert not parser.missing, f"Untranslated static interface copy in {path.name}: {sorted(parser.missing)}"
        for options in re.findall(r"{%\s*for\s+value\s*,\s*label\s+in\s+(.+?)\s*%}", source, flags=re.S):
            for _, label in ast.literal_eval(options):
                assert label in catalogue, f"Untranslated selector option in {path.name}: {label}"
