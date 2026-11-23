"""Only application-owned strings are eligible for translation, never customer data."""
from functools import lru_cache
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def application_strings():
    result = set()
    for folder in ("templates", "routers", "static/saas", "static/v2"):
        for path in (ROOT / folder).rglob("*"):
            if not path.is_file() or path.suffix not in {".html", ".py", ".js"}:
                continue
            source = path.read_text(encoding="utf-8")
            for text in re.findall(r">([^<>\n]{2,500})<", source):
                value = re.sub(r"\s+", " ", text).strip()
                if re.search(r"[А-Яа-яІіЇїЄєҐґ]", value) and not any(x in value for x in ("{", "}", "${")):
                    result.add(value)
    catalog = ROOT / "static" / "locales" / "catalog.json"
    if catalog.exists():
        result.update(json.loads(catalog.read_text(encoding="utf-8")).keys())
    return result
