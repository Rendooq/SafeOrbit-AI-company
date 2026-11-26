"""Run, save and export the constructor's optional calculators and registers."""
import json
import re
from collections import Counter
from datetime import date
from decimal import Decimal, DecimalException

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from database import get_db
from models_platform import WorkspaceRecord
from routers.workspace import redirect, shell, workspace_user
from services.marketplace import lock_calendar
from services.workspace_catalog import allowed_modules
from services.workspace_tools import ToolError, csv_report, website_url
from services.workflows import WORKFLOWS


router = APIRouter(prefix="/workspace/tools")
MAX_SAVED = 250
PAGE_SIZE = 20


def workflow(key, user):
    if key not in WORKFLOWS or key not in allowed_modules(user.business):
        raise HTTPException(404)
    return WORKFLOWS[key]


async def record(db, user, key, record_id):
    found = await db.scalar(select(WorkspaceRecord).where(
        WorkspaceRecord.business_id == user.business_id, WorkspaceRecord.module == key, WorkspaceRecord.id == record_id
    ))
    if not found:
        raise HTTPException(404)
    return found


def error_text(field, error):
    if isinstance(error, ToolError):
        return f"{field.label} · {error}"
    return f"Перевірте значення поля «{field.label}»."


async def read_fields(spec, form):
    original, typed = {}, []
    for field in spec.fields:
        name = "f_" + field.key
        raw = form.get(name, "")
        if not isinstance(raw, str):
            raise ToolError("Перевірте поля форми.")
        upload = form.get(name + "_file") if field.kind == "csv" else None
        if not raw.strip() and isinstance(upload, UploadFile) and upload.filename:
            try:
                raw = (await upload.read(120001)).decode("utf-8-sig")
            except UnicodeError as error:
                raise ToolError("Збережіть таблицю CSV у кодуванні UTF-8.") from error
        value = raw.strip()
        original[field.key] = value
        limit = 120000 if field.kind == "csv" else 16000 if field.kind == "long" else 2048 if field.kind == "url" else 250
        if len(value) > limit or (field.required and not value):
            raise ToolError(f"Заповніть поле «{field.label}» (до {limit} символів).")
        converted = value
        try:
            if value and field.kind in {"number", "signed"}:
                converted = Decimal(value.replace(",", "."))
                minimum = -1000000000 if field.kind == "signed" else 0
                if not converted.is_finite() or not minimum <= converted <= 1000000000 or converted.as_tuple().exponent < -8:
                    raise ValueError()
                original[field.key] = format(converted, "f")
            elif value and field.kind == "date":
                parsed = date.fromisoformat(value)
                if not 1900 <= parsed.year <= 2200:
                    raise ValueError()
                converted = parsed.isoformat()
                original[field.key] = converted
            elif value and field.kind == "time" and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                raise ValueError()
            elif value and field.kind == "url":
                converted = website_url(value)
        except (ValueError, DecimalException) as error:
            raise ToolError(error_text(field, error)) from error
        typed.append(converted)
    return original, typed


def run_calculation(spec, values):
    answer = spec.operation(*values)
    if isinstance(answer, Decimal):
        return format(answer, ".2f")
    return str(answer)


async def page(key, spec, user, db, *, q="", status_filter="", page_number=1, error="", editing=None, values=None, title="", status_code=200):
    existing = (await db.scalars(select(WorkspaceRecord).where(
        WorkspaceRecord.business_id == user.business_id, WorkspaceRecord.module == key
    ).order_by(WorkspaceRecord.id.desc()).limit(MAX_SAVED))).all()
    existing = [(row, json.loads(row.data)) for row in existing]
    query = q.strip()[:120].casefold()
    filtered = [(row, saved) for row, saved in existing if (
        (not status_filter or saved.get("status") == status_filter)
        and (not query or query in " ".join([row.title, *saved.get("values", {}).values()]).casefold())
    )]
    counts = Counter(saved.get("status") for _, saved in existing)
    totals = {field.label: f"{sum(Decimal(saved['values'][field.key] or '0') for _, saved in filtered):.2f}"
              for field in spec.fields if field.key in spec.aggregate}
    max_page = max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
    page_number = max(1, min(page_number, max_page))
    return shell("tool-workflow", workspace_nav=True, key=key, spec=spec, status=status_code, error=error, q=q,
                 records=filtered[(page_number-1)*PAGE_SIZE:page_number*PAGE_SIZE],
                 editing=editing, values=values or {}, title=title, status_filter=status_filter, states=counts, totals=totals,
                 page_number=page_number, max_page=max_page, default_status=(editing[1].get("status") if editing else ""),
                 count=len(filtered), total_count=len(existing))


@router.get("/{key}")
async def show(key: str, request: Request, q: str = "", state: str = "", p: int = 1,
               user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    spec = workflow(key, user)
    return await page(key, spec, user, db, q=q, status_filter=state if state in spec.statuses else "", page_number=p)


@router.post("/{key}")
async def save(key: str, request: Request, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    spec = workflow(key, user)
    form = await request.form()
    title = str(form.get("title", "")).strip()
    oid = str(form.get("record_id", ""))
    saved = None
    if oid:
        if not oid.isascii() or not oid.isdigit() or len(oid) > 12 or spec.mode != "register":
            raise HTTPException(422)
        saved = await record(db, user, key, int(oid))
    values = {}
    try:
        if not 1 <= len(title) <= 160:
            raise ToolError("Вкажіть назву до 160 символів.")
        values, arguments = await read_fields(spec, form)
        data = {"values": values}
        if spec.mode == "calc":
            data["answer"] = run_calculation(spec, arguments)
        elif spec.mode == "transform":
            data["result"] = await run_in_threadpool(spec.operation, arguments)
        elif spec.mode == "register":
            state = form.get("state")
            if state not in spec.statuses:
                raise ToolError("Оберіть статус.")
            data["status"] = state
            if key == "time_off" and arguments[1] > arguments[2]:
                raise ToolError("Дата початку не може бути пізнішою за завершення.")
            if key == "inspections" and arguments[1] > arguments[2]:
                raise ToolError("Пройдених пунктів більше за загальну кількість.")
        serialized = json.dumps(data, ensure_ascii=False)
        if len(serialized) > 320000:
            raise ToolError("Результат завеликий. Поділіть вхідні дані.")
    except (DecimalException, OverflowError, ValueError) as error:
        message = str(error) if isinstance(error, ToolError) else "Перевірте формат і діапазон даних."
        return await page(key, spec, user, db, error=message, values=values, title=title, status_code=422,
                          editing=(saved, json.loads(saved.data)) if saved else None)
    if not saved:
        await lock_calendar(db, user.business_id)
        count = await db.scalar(select(func.count(WorkspaceRecord.id)).where(
            WorkspaceRecord.business_id == user.business_id, WorkspaceRecord.module == key))
        if count >= MAX_SAVED:
            return await page(key, spec, user, db, error=f"Ліміт {MAX_SAVED} записів. Експортуйте й видаліть старі дані.",
                              values=values, title=title, status_code=422)
        saved = WorkspaceRecord(business_id=user.business_id, module=key, title=title, data=serialized)
        db.add(saved)
    else:
        saved.title, saved.data = title, serialized
    await db.commit()
    return redirect(f"/workspace/tools/{key}#record-{saved.id}")


@router.get("/{key}/records/{record_id}/edit")
async def edit(key: str, record_id: int, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    spec = workflow(key, user)
    if spec.mode != "register":
        raise HTTPException(404)
    saved = await record(db, user, key, record_id)
    data = json.loads(saved.data)
    return await page(key, spec, user, db, editing=(saved, data), values=data["values"], title=saved.title)


@router.post("/{key}/records/{record_id}/delete")
async def drop(key: str, record_id: int, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    workflow(key, user)
    saved = await record(db, user, key, record_id)
    await db.delete(saved)
    await db.commit()
    return redirect(f"/workspace/tools/{key}")


def export(key, headers, rows):
    return Response(csv_report(headers, rows), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="safeorbit-{key}.csv"'})


@router.get("/{key}/export")
async def export_register(key: str, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    spec = workflow(key, user)
    if spec.mode == "transform":
        raise HTTPException(404)
    existing = (await db.scalars(select(WorkspaceRecord).where(
        WorkspaceRecord.business_id == user.business_id, WorkspaceRecord.module == key
    ).order_by(WorkspaceRecord.id.desc()).limit(MAX_SAVED))).all()
    rows = []
    for row in existing:
        data = json.loads(row.data)
        rows.append([row.title, *(data["values"].get(field.key, "") for field in spec.fields),
                     data.get("status", data.get("answer", ""))])
    return export(key, ["Назва", *(field.label for field in spec.fields), "Статус" if spec.mode == "register" else spec.output], rows)


@router.get("/{key}/records/{record_id}/export")
async def export_result(key: str, record_id: int, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    spec = workflow(key, user)
    if spec.mode != "transform":
        raise HTTPException(404)
    saved = await record(db, user, key, record_id)
    result = json.loads(saved.data)["result"]
    return export(key, result["headers"], result["rows"])
