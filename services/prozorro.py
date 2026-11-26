"""Fetch public tender metadata from Prozorro's read-only API."""
import json
import re

import httpx

from services.workspace_tools import ToolError


async def tender_snapshot(reference):
    match = re.fullmatch(r"(?:https://public-api\.prozorro\.gov\.ua/api/2\.5/tenders/)?([0-9a-f]{32})/?", reference)
    if not match:
        raise ToolError("Вкажіть внутрішній ID Prozorro з 32 символів або посилання public-api.prozorro.gov.ua.")
    identifier = match[1]
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            async with client.stream("GET", f"https://public-api.prozorro.gov.ua/api/2.5/tenders/{identifier}") as response:
                if response.status_code == 404:
                    raise ToolError("Закупівлю не знайдено в Prozorro.")
                response.raise_for_status()
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > 2_000_000:
                        raise ToolError("Відповідь Prozorro завелика. Можна перевірити завантажений PDF окремо.")
        data = json.loads(chunks)["data"]
        code = data["tenderID"]
        if data["id"] != identifier or not re.fullmatch(r"UA-\d{4}-\d{2}-\d{2}-\d{6}-[a-z]", code):
            raise ValueError("Unexpected tender ID")
        documents = {doc["id"]: (str(doc.get("title", ""))[:160], str(doc.get("dateModified", ""))[:40])
                     for doc in data.get("documents", [])[:100] if isinstance(doc, dict) and isinstance(doc.get("id"), str)}
        return {"id": identifier, "code": code, "title": str(data.get("title", ""))[:300],
                "date": str(data.get("dateModified", ""))[:40], "status": str(data.get("status", ""))[:32],
                "source": f"https://prozorro.gov.ua/tender/{code}", "documents": documents}
    except ToolError:
        raise
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise ToolError("Не вдалося отримати дані Prozorro. Спробуйте ще раз або перевірте PDF окремо.") from exc


def document_changes(previous, current):
    older, newer = previous["documents"], current["documents"]
    changes = [(metadata[0], "Додано" if key not in older else "Оновлено") for key, metadata in newer.items()
               if key not in older or list(metadata) != list(older[key])]
    changes.extend((older[key][0], "Вилучено") for key in sorted(older.keys() - newer.keys()))
    return changes
