import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models_platform import WorkspaceTable, WorkspaceTableRow
from routers.workspace import redirect, shell, workspace_user
from services import workspace_tools
from services.marketplace import lock_calendar
from services.workspace_catalog import allowed_modules


router = APIRouter(prefix="/workspace/tables")
KINDS = {"text": "Текст", "number": "Число", "date": "Дата", "check": "Так / ні"}


async def table_user(user=Depends(workspace_user)):
    if "tables" not in allowed_modules(user.business):
        raise HTTPException(404)
    return user


async def owned(db, table_id, business_id):
    table = await db.scalar(select(WorkspaceTable).where(
        WorkspaceTable.business_id == business_id, WorkspaceTable.id == table_id))
    if not table:
        raise HTTPException(404)
    return table


@router.get("")
async def tables(user=Depends(table_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(WorkspaceTable).where(
        WorkspaceTable.business_id == user.business_id).order_by(WorkspaceTable.id))).all()
    return shell("tables", workspace_nav=True, tables=rows, kinds=KINDS)


@router.post("")
async def create_table(request: Request, user=Depends(table_user), db: AsyncSession = Depends(get_db)):
    form = await request.form()
    title = str(form.get("title", "")).strip()
    names, kinds = form.getlist("name"), form.getlist("kind")
    if len(names) != len(kinds) or not 1 <= len(names) <= 12 or not 1 <= len(title) <= 120:
        raise HTTPException(422, "Перевірте назву і кількість полів.")
    fields = [(str(name).strip(), kind) for name, kind in zip(names, kinds) if str(name).strip()]
    if (not fields or len({name.casefold() for name, _ in fields}) != len(fields)
            or not all(len(name) <= 70 and kind in KINDS for name, kind in fields)):
        raise HTTPException(422, "Заповніть поля й уникайте повторів.")
    await lock_calendar(db, user.business_id)
    count = await db.scalar(select(func.count(WorkspaceTable.id)).where(WorkspaceTable.business_id == user.business_id))
    if count >= 30:
        raise HTTPException(422, "До 30 власних таблиць на простір.")
    table = WorkspaceTable(business_id=user.business_id, title=title, fields=json.dumps(fields, ensure_ascii=False))
    db.add(table)
    await db.commit()
    return redirect(f"/workspace/tables/{table.id}")


@router.get("/{table_id}")
async def show_table(table_id: int, user=Depends(table_user), db: AsyncSession = Depends(get_db)):
    table = await owned(db, table_id, user.business_id)
    rows = (await db.scalars(select(WorkspaceTableRow).where(
        WorkspaceTableRow.table_id == table.id).order_by(WorkspaceTableRow.id.desc()).limit(1000))).all()
    return shell("table", workspace_nav=True, table=table, fields=json.loads(table.fields),
                 rows=[(row.id, json.loads(row.cells)) for row in rows])


@router.post("/{table_id}/rows")
async def add_row(table_id: int, request: Request, user=Depends(table_user), db: AsyncSession = Depends(get_db)):
    await lock_calendar(db, user.business_id)
    table = await owned(db, table_id, user.business_id)
    form = await request.form()
    fields = json.loads(table.fields)
    values = []
    for idx, (_, kind) in enumerate(fields):
        value = str(form.get(f"value_{idx}", "")).strip()
        try:
            if len(value) > 2400:
                raise ValueError()
            if kind == "date" and value:
                value = date.fromisoformat(value).isoformat()
            if kind == "number" and value:
                value = workspace_tools.printable(workspace_tools.amount(value, minimum=-1000000000))
        except ValueError as exc:
            raise HTTPException(422, "Перевірте введені значення.") from exc
        if kind == "check":
            value = "так" if value == "yes" else "ні"
        values.append(value)
    count = await db.scalar(select(func.count(WorkspaceTableRow.id)).where(WorkspaceTableRow.table_id == table.id))
    if count >= 1000 or not any(values):
        raise HTTPException(422, "Заповніть рядок. У таблиці може бути до 1000 рядків.")
    db.add(WorkspaceTableRow(table_id=table.id, cells=json.dumps(values, ensure_ascii=False)))
    await db.commit()
    return redirect(f"/workspace/tables/{table.id}")


@router.post("/{table_id}/rows/{row_id}/delete")
async def remove_row(table_id: int, row_id: int, user=Depends(table_user), db: AsyncSession = Depends(get_db)):
    await owned(db, table_id, user.business_id)
    await db.execute(delete(WorkspaceTableRow).where(WorkspaceTableRow.table_id == table_id, WorkspaceTableRow.id == row_id))
    await db.commit()
    return redirect(f"/workspace/tables/{table_id}")


@router.get("/{table_id}/export")
async def export_table(table_id: int, user=Depends(table_user), db: AsyncSession = Depends(get_db)):
    table = await owned(db, table_id, user.business_id)
    rows = (await db.scalars(select(WorkspaceTableRow.cells).where(
        WorkspaceTableRow.table_id == table_id).order_by(WorkspaceTableRow.id))).all()
    data = workspace_tools.csv_report([name for name, _ in json.loads(table.fields)], [json.loads(row) for row in rows])
    return Response(data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="table-{table_id}.csv"'})


@router.post("/{table_id}/delete")
async def remove_table(table_id: int, user=Depends(table_user), db: AsyncSession = Depends(get_db)):
    await lock_calendar(db, user.business_id)
    table = await owned(db, table_id, user.business_id)
    await db.execute(delete(WorkspaceTableRow).where(WorkspaceTableRow.table_id == table_id))
    await db.delete(table)
    await db.commit()
    return redirect("/workspace/tables")
