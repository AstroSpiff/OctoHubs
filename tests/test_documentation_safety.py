from pathlib import Path
import re


DOCUMENTATION_ROOTS = (Path("README.md"), Path("README_ita.md"), Path("docs"))
LITERAL_EMBY_API_KEY = re.compile(r"(?i)\bapi_key\s*=\s*[\"']?([a-f0-9]{24,})")


def _documentation_files():
    for root in DOCUMENTATION_ROOTS:
        if root.is_file():
            yield root
        elif root.is_dir():
            yield from root.rglob("*.md")


def test_documentation_does_not_contain_literal_emby_api_keys():
    exposed = []
    for path in _documentation_files():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if LITERAL_EMBY_API_KEY.search(line):
                exposed.append(f"{path}:{line_number}")

    assert not exposed, "Literal Emby API keys found in documentation: " + ", ".join(exposed)
