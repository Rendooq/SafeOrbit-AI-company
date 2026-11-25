"""Business presets, tenant-scoped tools and constructor."""
import base64
import binascii
import hashlib
import io
import json
import os
import re
import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as FormUpload

from database import get_db
from dependencies import get_current_user
from models import Business, User
from models_platform import BookShare, CheckoutProbe, WorkspaceAttachment, WorkspaceLayout, WorkspaceRecord
from services import workspace_tools as tools
from services.workspace_catalog import INDUSTRIES, MODULES, PLAN_NAMES, allowed_modules
from utils.templates import render_template


router = APIRouter()
ACCENTS = {"violet": "Фіолетовий", "ocean": "Синій", "fern": "Зелений", "copper": "Мідний"}
WIDTHS = {"normal": "Звичайна", "wide": "Широка"}
SPACING = {"relaxed": "Вільні", "compact": "Компактні"}
MEDIA = {
    "pdf": "application/pdf", "jpg": "image/jpeg", "png": "image/png",
    "mp3": "audio/mpeg", "ogg": "audio/ogg", "webm": "audio/webm",
    "wav": "audio/wav", "m4a": "audio/mp4",
}
OWNER = {"owner", "admin"}

FORMATS = {
    "reconcile": ("ttn;amount", "Очікувані виплати", "Реєстр виплат"),
    "invoices": ("item;unit;package;price;ordered", "Попередня накладна", "Поточна накладна"),
    "cutting": ("part;width;height;qty;rotate", "Деталі", ""),
    "cars": ("url;model;year;km;price;notes", "Оголошення", ""),
}
EXPORTS = {"reconcile", "invoices", "feeds", "tender", "cutting", "preflight", "cars", "budget", "time"}


def shell(template, *, status=200, **data):
    return HTMLResponse(render_template("platform/" + template + ".html", **data), status_code=status)


def active_owner(user):
    return user and user.role in OWNER and user.business_id and user.business and not getattr(user, "is_demo_workspace", False)


def redirect(path):
    return RedirectResponse(path, status_code=303)


async def workspace_user(user: User = Depends(get_current_user)):
    if not active_owner(user):
        raise HTTPException(403, "Потрібен доступ власника робочого простору.")
    return user


@router.get("/workspace")
async def workspace(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not active_owner(user):
        return redirect("/login")
    return await workspace_page(user, db)


async def workspace_page(user, db, error="", status=200):
    business = user.business
    allowed = allowed_modules(business)
    stored = await db.get(WorkspaceLayout, business.id)
    settings = json.loads(stored.settings) if stored else {}
    industry = INDUSTRIES.get(business.type)
    default = (INDUSTRIES["other"].modules if business.plan_type == "custom" else industry.modules if industry else allowed[:6])
    layout = [key for key in settings.get("layout", default) if key in allowed]
    return shell(
        "workspace", status=status, business=business, catalog=MODULES, settings=settings, layout=layout,
        accents=ACCENTS, widths=WIDTHS, spacing=SPACING, available=[key for key in allowed if key not in layout],
        industry=INDUSTRIES.get(business.type), plan_name=PLAN_NAMES.get(business.plan_type, "Business"),
        custom=business.plan_type == "custom", error=error,
    )


@router.post("/workspace/layout")
async def save_layout(request: Request, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    form = await request.form()
    layout = list(dict.fromkeys(form.getlist("layout")))
    if not layout or any(key not in allowed_modules(user.business) for key in layout):
        return await workspace_page(user, db, "Виберіть хоча б один доступний модуль.", 422)
    accent, width, spacing = (form.get(name) for name in ("accent", "width", "spacing"))
    if accent not in ACCENTS or width not in WIDTHS or spacing not in SPACING:
        return await workspace_page(user, db, "Перевірте параметри оформлення.", 422)
    settings = json.dumps({"layout": layout, "accent": accent, "width": width, "spacing": spacing,
                           "title": str(form.get("title", "")).strip()[:100],
                           "wide_modules": [key for key in layout if form.get(f"tile_{key}") == "wide"]},
                          ensure_ascii=False)
    current = await db.get(WorkspaceLayout, user.business_id)
    if current:
        current.settings = settings
    else:
        db.add(WorkspaceLayout(business_id=user.business_id, settings=settings))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        await db.execute(update(WorkspaceLayout).where(WorkspaceLayout.business_id == user.business_id).values(settings=settings))
        await db.commit()
    return redirect("/workspace")


def check_module(module, user):
    if module not in allowed_modules(user.business) or MODULES[module].path:
        raise HTTPException(404)


async def tenant_record(record_id, user, db):
    record = await db.scalar(select(WorkspaceRecord).where(
        WorkspaceRecord.business_id == user.business_id, WorkspaceRecord.id == record_id))
    if not record:
        raise HTTPException(404)
    check_module(record.module, user)
    return record


def form_text(form, field, limit=160, optional=False):
    value = form.get(field, "")
    if not isinstance(value, str) or len(value) > limit or (not optional and not value.strip()):
        raise tools.ToolError("Заповніть усі обов’язкові поля та перевірте довжину.")
    return value.strip()


async def uploaded(form, name="file", kinds=None, optional=False):
    file = form.get(name)
    if not isinstance(file, FormUpload) or not file.filename:
        if optional:
            return None
        raise tools.ToolError("Додайте файл.")
    filename = file.filename.replace("\\", "/").split("/")[-1][:160]
    ext = filename.rsplit(".", 1)[-1].casefold()
    payload = await file.read(4 * 1024 * 1024 + 1)
    checks = {
        "pdf": payload.startswith(b"%PDF-"), "jpg": payload.startswith(b"\xff\xd8\xff"),
        "png": payload.startswith(b"\x89PNG\r\n\x1a\n"), "ogg": payload.startswith(b"OggS"),
        "mp3": payload.startswith(b"ID3") or (len(payload) > 1 and payload[0] == 255 and payload[1] & 224 == 224),
        "webm": payload.startswith(b"\x1a\x45\xdf\xa3"),
        "wav": payload.startswith(b"RIFF") and payload[8:12] == b"WAVE",
        "m4a": payload[4:8] == b"ftyp",
    }
    if not 0 < len(payload) <= 4 * 1024 * 1024 or not checks.get(ext) or (kinds and ext not in kinds):
        raise tools.ToolError("Тип файлу не підтримується або розмір перевищує 4 МБ.")
    return filename, MEDIA[ext], payload


async def input_text(form, field, *, excel=False):
    value = form.get(field, "")
    if isinstance(value, FormUpload):
        value = await value.read(450001)
        try:
            return value.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise tools.ToolError("Збережіть файл у кодуванні UTF-8.") from exc
    upload = form.get(field + "_file")
    if isinstance(upload, FormUpload) and upload.filename and not value:
        if excel and upload.filename.casefold().endswith(".xlsx"):
            contents = await upload.read(4000001)
            if len(contents) > 4000000:
                raise tools.ToolError("Розмір XLSX має бути меншим за 4 МБ.")
            value = await run_in_threadpool(tools.workbook_csv, contents)
        else:
            try:
                value = (await upload.read(450001)).decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise tools.ToolError("Збережіть файл у кодуванні UTF-8.") from exc
    if len(value) > 450000:
        raise tools.ToolError("Текстовий файл має бути меншим за 450 КБ.")
    return value


async def tool_result(module, form):
    if module in {"reconcile", "invoices"}:
        return await run_in_threadpool(getattr(tools, module), await input_text(form, "first", excel=module == "reconcile"),
                                       await input_text(form, "second", excel=module == "reconcile")), None
    if module == "feeds":
        return await run_in_threadpool(tools.feeds, await input_text(form, "first"), await input_text(form, "second")), None
    if module in {"tender", "preflight"}:
        _, _, pdf = await uploaded(form, kinds={"pdf"})
        if module == "tender":
            return await run_in_threadpool(tools.tender, form_text(form, "body", 16000),
                                           form_text(form, "previous", 16000, True), pdf), None
        return await run_in_threadpool(tools.preflight, pdf, *(form.get(key) for key in ("width", "height", "bleed", "dpi"))), None
    if module == "cutting":
        return await run_in_threadpool(tools.cutting, await input_text(form, "first"),
                                       *(form.get(key) for key in ("width", "height", "kerf"))), None
    if module == "cars":
        rows = []
        for url, model, year, km, price, notes in tools.table(await input_text(form, "first"), ("url", "model", "year", "km", "price", "notes")):
            if len(rows) >= 25 or not re.fullmatch(r"(19|20)[0-9]{2}", year):
                raise tools.ToolError("Вкажіть коректний рік і до 25 оголошень.")
            rows.append([tools.website_url(url), model, year, str(int(tools.amount(km))), tools.printable(tools.amount(price)), notes])
        rows.sort(key=lambda row: float(row[4]))
        return tools.report(["Оголошення", "Модель", "Рік", "Км", "Ціна, PLN", "Зауваження"], rows,
                            "Порівняння за ціною. Звірте VIN, запис про пробіг і стан на огляді.",
                            questions=["Czy może Pan/Pani podać VIN, numer rejestracyjny i datę pierwszej rejestracji?",
                                       "Czy są faktury za serwis i naprawy?",
                                       "Czy mogę sprawdzić samochód w niezależnym warsztacie?"]), None
    if module == "extras":
        rows = [[name, tools.printable(tools.amount(cost))]
                for name, cost in tools.table(await input_text(form, "first"), ("item", "cost"))]
        if len(rows) > 60:
            raise tools.ToolError("В одному погодженні може бути до 60 робіт.")
        return tools.report(["Робота", "Сума, грн"], rows, f"Разом: {sum(tools.amount(row[1]) for row in rows):.2f} грн",
                            token=secrets.token_urlsafe(24), state="pending", extra_days=int(tools.amount(form.get("days"), maximum=365)),
                            description=form_text(form, "body", 3000, True)), await uploaded(form, kinds={"jpg", "png"}, optional=True)
    body = form_text(form, "body", 12000, optional=module in {"links", "tasks", "contacts", "files", "budget", "time", "book"})
    data = {"body": body}
    attachment = None
    if module == "tasks":
        due = form_text(form, "due", 10, True)
        if due:
            try:
                date.fromisoformat(due)
            except ValueError as exc:
                raise tools.ToolError("Перевірте дату.") from exc
        data.update(due=due, done=form.get("done") == "yes")
    if module == "budget":
        direction = form.get("direction")
        if direction not in {"income", "expense"}:
            raise tools.ToolError("Оберіть тип операції.")
        data.update(value=tools.printable(tools.amount(form.get("value"))), direction=direction)
    if module == "time":
        hours, rate = (tools.amount(form.get(key)) for key in ("hours", "rate"))
        data.update(hours=tools.printable(hours), rate=tools.printable(rate), value=tools.printable(hours * rate))
    if module == "links":
        data["url"] = tools.website_url(form_text(form, "url", 2000))
    if module == "contacts":
        data["contact"] = form_text(form, "contact", 300)
    if module in {"book", "files"}:
        attachment = await uploaded(form, kinds=set(MEDIA) if module == "files" else {"mp3", "ogg", "webm", "wav", "m4a", "jpg", "png"},
                                    optional=module == "book")
        if not body and not attachment:
            raise tools.ToolError("Додайте текст або запис.")
    return data, attachment


async def module_page(module, user, db, error="", status=200, editing=None):
    check_module(module, user)
    records = (await db.scalars(select(WorkspaceRecord).where(
        WorkspaceRecord.business_id == user.business_id, WorkspaceRecord.module == module
    ).order_by(WorkspaceRecord.id.desc()).limit(100))).all()
    ids = [record.id for record in records]
    attachment_rows = (await db.execute(select(WorkspaceAttachment.id, WorkspaceAttachment.record_id, WorkspaceAttachment.filename,
                                              WorkspaceAttachment.media_type).where(WorkspaceAttachment.record_id.in_(ids)))).all()
    attachments = defaultdict(list)
    for attachment in attachment_rows:
        attachments[attachment.record_id].append(attachment)
    rows = [(record, json.loads(record.data), attachments[record.id]) for record in records]
    total = None
    if module == "budget":
        total = f"{sum((1 if data['direction'] == 'income' else -1) * tools.amount(data['value']) for _, data, _ in rows):.2f}"
    if module == "time":
        total = f"{sum(float(data['value']) for _, data, _ in rows):.2f}"
    probes = []
    if module == "checkout":
        probes = (await db.scalars(select(CheckoutProbe).where(CheckoutProbe.business_id == user.business_id))).all()
    return shell("module", status=status, key=module, module=MODULES[module], rows=rows, error=error,
                 format=FORMATS.get(module), export=module in EXPORTS, total=total, probes=probes, editing=editing,
                 transcribe=bool(os.getenv("WORKSPACE_TRANSCRIPTION_KEY")) and module == "book")


@router.get("/workspace/module/{module}")
async def show_module(module: str, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    return await module_page(module, user, db)


@router.post("/workspace/module/{module}")
async def save_record(module: str, request: Request, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    check_module(module, user)
    if module == "checkout":
        raise HTTPException(405)
    form = await request.form()
    try:
        title = form_text(form, "title")
        record_id = form_text(form, "record_id", 12, True)
        record = None
        if record_id:
            if not record_id.isdecimal() or module not in {"notes", "tasks", "decisions", "contacts", "links"}:
                raise tools.ToolError("Цей запис неможливо редагувати.")
            record = await tenant_record(int(record_id), user, db)
            if record.module != module:
                raise HTTPException(404)
        result, attachment = await tool_result(module, form)
        if not record:
            record = WorkspaceRecord(business_id=user.business_id, module=module, title=title, data="{}")
            db.add(record)
        record.title, record.data = title, json.dumps(result, ensure_ascii=False)
        await db.flush()
        if attachment:
            filename, media_type, data = attachment
            db.add(WorkspaceAttachment(record_id=record.id, filename=filename, media_type=media_type, content=data))
        await db.commit()
    except (tools.ToolError, ValueError) as error:
        return await module_page(module, user, db, str(error), 422)
    return redirect(f"/workspace/module/{module}#record-{record.id}")


@router.get("/workspace/records/{record_id}/edit")
async def edit_record(record_id: int, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    record = await tenant_record(record_id, user, db)
    if record.module not in {"notes", "tasks", "decisions", "contacts", "links"}:
        raise HTTPException(405)
    return await module_page(record.module, user, db, editing=(record, json.loads(record.data)))


@router.post("/workspace/records/{record_id}/delete")
async def delete_record(record_id: int, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    record = await tenant_record(record_id, user, db)
    module = record.module
    await db.execute(delete(WorkspaceAttachment).where(WorkspaceAttachment.record_id == record.id))
    await db.delete(record)
    await db.commit()
    return redirect(f"/workspace/module/{module}")


def asset_response(filename, media_type, content):
    disposition = "inline" if media_type.startswith(("audio/", "image/")) else "attachment"
    return Response(content, media_type=media_type, headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename, safe='')}",
        "Cache-Control": "private, no-store",
    })


@router.get("/workspace/attachments/{attachment_id}")
async def read_asset(attachment_id: int, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    record_id = await db.scalar(select(WorkspaceAttachment.record_id).where(WorkspaceAttachment.id == attachment_id))
    if record_id is None:
        raise HTTPException(404)
    await tenant_record(record_id, user, db)
    asset = (await db.execute(select(WorkspaceAttachment.filename, WorkspaceAttachment.media_type,
        WorkspaceAttachment.content).where(WorkspaceAttachment.id == attachment_id))).first()
    if not asset:
        raise HTTPException(404)
    return asset_response(*asset)


@router.get("/workspace/records/{record_id}/export")
async def export_record(record_id: int, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    record = await tenant_record(record_id, user, db)
    data = json.loads(record.data)
    if "headers" not in data:
        raise HTTPException(404)
    return Response(tools.csv_report(data["headers"], data["rows"]), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{record.module}-{record.id}.csv"'})


async def book_page(db, business, owner=False, share=None):
    records = (await db.scalars(select(WorkspaceRecord).where(
        WorkspaceRecord.business_id == business.id, WorkspaceRecord.module == "book").order_by(WorkspaceRecord.id))).all()
    assets = (await db.execute(select(WorkspaceAttachment.id, WorkspaceAttachment.record_id, WorkspaceAttachment.media_type)
              .where(WorkspaceAttachment.record_id.in_([record.id for record in records])))).all()
    indexed = defaultdict(list)
    for asset in assets:
        indexed[asset.record_id].append(asset)
    return shell("book", business=business.name, owner=owner, share=share, chapters=[
        (record, json.loads(record.data), indexed[record.id]) for record in records])


@router.get("/workspace/book/print")
async def print_book(user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    check_module("book", user)
    share = await db.get(BookShare, user.business_id)
    return await book_page(db, user.business, owner=True, share=share)


@router.post("/workspace/book/share")
async def change_book_share(request: Request, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    check_module("book", user)
    form = await request.form()
    share = await db.get(BookShare, user.business_id)
    if form.get("share") == "yes" and share is None:
        db.add(BookShare(business_id=user.business_id, token=secrets.token_urlsafe(32)))
    elif form.get("share") != "yes" and share:
        await db.delete(share)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
    return redirect("/workspace/book/print")


async def shared_book(db, token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise HTTPException(404)
    share = await db.scalar(select(BookShare).where(BookShare.token == token))
    business = await db.get(Business, share.business_id) if share else None
    if not business or not business.is_active or "book" not in allowed_modules(business):
        raise HTTPException(404)
    return business, share


@router.get("/books/{token}")
async def view_shared_book(token: str, db: AsyncSession = Depends(get_db)):
    business, share = await shared_book(db, token)
    return await book_page(db, business, share=share)


async def shared_asset(db, token, attachment_id, content=False):
    business, _ = await shared_book(db, token)
    fields = [WorkspaceAttachment.filename, WorkspaceAttachment.media_type]
    if content:
        fields.append(WorkspaceAttachment.content)
    asset = (await db.execute(select(*fields).join(WorkspaceRecord, WorkspaceRecord.id == WorkspaceAttachment.record_id)
             .where(WorkspaceRecord.business_id == business.id, WorkspaceRecord.module == "book",
                    WorkspaceAttachment.id == attachment_id))).first()
    if not asset:
        raise HTTPException(404)
    return asset


@router.get("/books/{token}/audio/{attachment_id}")
async def audio_page(token: str, attachment_id: int, db: AsyncSession = Depends(get_db)):
    filename, mime = await shared_asset(db, token, attachment_id)
    if not mime.startswith("audio/"):
        raise HTTPException(404)
    return shell("book-audio", token=token, filename=filename, attachment_id=attachment_id)


@router.get("/books/{token}/asset/{attachment_id}")
async def read_shared_asset(token: str, attachment_id: int, db: AsyncSession = Depends(get_db)):
    return asset_response(*(await shared_asset(db, token, attachment_id, content=True)))


@router.get("/books/{token}/qr/{attachment_id}")
async def book_qr(token: str, attachment_id: int, db: AsyncSession = Depends(get_db)):
    _, mime = await shared_asset(db, token, attachment_id)
    if not mime.startswith("audio/"):
        raise HTTPException(404)
    import qrcode

    out = io.BytesIO()
    image = qrcode.make(f"https://safeorbit.com.pl/books/{token}/audio/{attachment_id}")
    image.save(out, format="PNG")
    return Response(out.getvalue(), media_type="image/png")


@router.post("/workspace/records/{record_id}/transcribe")
async def transcribe_book(record_id: int, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    record = await tenant_record(record_id, user, db)
    key = os.getenv("WORKSPACE_TRANSCRIPTION_KEY", "")
    if record.module != "book" or not key:
        raise HTTPException(404)
    data = json.loads(record.data)
    if data.get("body"):
        return await module_page("book", user, db, "У розділі вже є текст.", 409)
    asset = (await db.execute(select(WorkspaceAttachment.filename, WorkspaceAttachment.media_type, WorkspaceAttachment.content)
             .where(WorkspaceAttachment.record_id == record.id, WorkspaceAttachment.media_type.startswith("audio/")).limit(1))).first()
    if not asset:
        raise HTTPException(404)
    name, mime, content = asset
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post("https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": "Bearer " + key}, files={"file": (name, content, mime)},
                data={"model": "whisper-large-v3-turbo", "response_format": "json"})
            response.raise_for_status()
            transcript = response.json().get("text", "").strip()
            if not transcript:
                raise ValueError("Empty transcript")
    except (httpx.HTTPError, ValueError, AttributeError):
        return await module_page("book", user, db, "Не вдалося розпізнати запис. Спробуйте інший файл.", 502)
    data["body"] = transcript[:12000]
    await db.execute(update(WorkspaceRecord).where(WorkspaceRecord.id == record.id, WorkspaceRecord.data == record.data)
                      .values(data=json.dumps(data, ensure_ascii=False)))
    await db.commit()
    return redirect(f"/workspace/module/book#record-{record.id}")


async def proposal(db, record_id, secret):
    record = await db.get(WorkspaceRecord, record_id)
    if not record or record.module != "extras" or not re.fullmatch(r"[A-Za-z0-9_-]{32}", secret):
        raise HTTPException(404)
    data = json.loads(record.data)
    owner = await db.get(Business, record.business_id)
    if not owner or not owner.is_active or not secrets.compare_digest(secret, data.get("token", "")):
        raise HTTPException(404)
    return record, data, owner


@router.get("/proposals/{record_id}/{secret}")
async def show_proposal(record_id: int, secret: str, db: AsyncSession = Depends(get_db)):
    record, data, owner = await proposal(db, record_id, secret)
    photo = await db.scalar(select(WorkspaceAttachment.id).where(WorkspaceAttachment.record_id == record.id).limit(1))
    return shell("proposal", record=record, data=data, business=owner.name, secret=secret, photo=photo)


@router.get("/proposals/{record_id}/{secret}/photo")
async def proposal_photo(record_id: int, secret: str, db: AsyncSession = Depends(get_db)):
    await proposal(db, record_id, secret)
    asset = (await db.execute(select(WorkspaceAttachment.filename, WorkspaceAttachment.media_type, WorkspaceAttachment.content)
             .where(WorkspaceAttachment.record_id == record_id).limit(1))).first()
    if not asset:
        raise HTTPException(404)
    return asset_response(*asset)


@router.post("/proposals/{record_id}/{secret}")
async def decide_proposal(record_id: int, secret: str, request: Request, db: AsyncSession = Depends(get_db)):
    record, data, _ = await proposal(db, record_id, secret)
    form = await request.form()
    action, name = form.get("action"), str(form.get("name", "")).strip()
    if action not in {"approved", "declined"} or not 1 <= len(name) <= 120:
        raise HTTPException(422, "Вкажіть ім’я та рішення.")
    if data["state"] == "pending":
        data.update(state=action, responded_by=name, responded_at=datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC"))
        await db.execute(update(WorkspaceRecord).where(WorkspaceRecord.id == record.id, WorkspaceRecord.data == record.data)
                         .values(data=json.dumps(data, ensure_ascii=False)))
        await db.commit()
    return redirect(f"/proposals/{record_id}/{secret}")


@router.post("/workspace/probes")
async def add_probe(request: Request, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    check_module("checkout", user)
    form = await request.form()
    host = str(form.get("domain", "")).strip().lower()
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}", host) or len(host) > 253:
        return await module_page("checkout", user, db, "Введіть домен магазину без https://.", 422)
    token = secrets.token_urlsafe(32)
    probe = CheckoutProbe(business_id=user.business_id, domain=host, token_hash=hashlib.sha256(token.encode()).hexdigest())
    db.add(probe)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return await module_page("checkout", user, db, "Цей домен уже додано.", 422)
    return shell("probe", probe=probe, token=token)


@router.post("/workspace/probes/{probe_id}/delete")
async def delete_probe(probe_id: int, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    check_module("checkout", user)
    await db.execute(delete(CheckoutProbe).where(CheckoutProbe.id == probe_id, CheckoutProbe.business_id == user.business_id))
    await db.commit()
    return redirect("/workspace/module/checkout")


@router.post("/signals/checkout/{probe_id}")
async def probe_result(probe_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not re.fullmatch(r"[\w-]{43}", token, flags=re.ASCII):
        raise HTTPException(401)
    probe = await db.get(CheckoutProbe, probe_id)
    if not probe or not secrets.compare_digest(probe.token_hash, hashlib.sha256(token.encode()).hexdigest()):
        raise HTTPException(401)
    business = await db.get(Business, probe.business_id)
    if not business or not business.is_active or "checkout" not in allowed_modules(business):
        raise HTTPException(403)
    if int(request.headers.get("content-length", "0")) > 900000:
        raise HTTPException(413)
    screenshot = None
    try:
        result = await request.json()
        host = urlsplit(result["url"]).hostname
        step = result["step"]
        result_ms = int(result["ms"])
        status = result["status"]
        if host != probe.domain or status not in {"ok", "failed"} or not isinstance(step, str) or not 1 <= len(step) <= 160 or not 0 <= result_ms <= 180000:
            raise ValueError()
        if result.get("screenshot"):
            screenshot = base64.b64decode(result["screenshot"], validate=True)
            if status != "failed" or not screenshot.startswith(b"\x89PNG\r\n\x1a\n") or len(screenshot) > 450000:
                raise ValueError()
    except (ValueError, TypeError, KeyError, binascii.Error):
        raise HTTPException(422, "Invalid probe result.")
    await db.execute(update(Business).where(Business.id == business.id).values(id=Business.id))
    latest = await db.scalar(select(WorkspaceRecord.created_at).where(
        WorkspaceRecord.business_id == business.id, WorkspaceRecord.module == "checkout", WorkspaceRecord.title == probe.domain
    ).order_by(WorkspaceRecord.id.desc()).limit(1))
    if latest and latest.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) - timedelta(seconds=25):
        raise HTTPException(429, "Wait at least 25 seconds between results.")
    data = json.dumps({"body": step, "status": status, "ms": result_ms})
    record = WorkspaceRecord(business_id=business.id, module="checkout", title=probe.domain, data=data)
    db.add(record)
    await db.flush()
    if screenshot:
        db.add(WorkspaceAttachment(record_id=record.id, filename="checkout-failure.png", media_type="image/png", content=screenshot))
    older = select(WorkspaceRecord.id).where(WorkspaceRecord.business_id == business.id, WorkspaceRecord.module == "checkout"
                                            ).order_by(WorkspaceRecord.id.desc()).offset(100).limit(500)
    await db.execute(delete(WorkspaceAttachment).where(WorkspaceAttachment.record_id.in_(older)))
    await db.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id.in_(older)))
    await db.commit()
    return Response(status_code=204)
