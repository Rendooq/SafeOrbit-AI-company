import asyncio
import json
from decimal import Decimal

from test_platform import post, seed, test_app
from sqlalchemy import select

from models import Business
from models_platform import WorkspaceRecord
from services.workspace_catalog import MODULES
from services.workflows import WORKFLOWS


TRANSFORM_EXAMPLES = {
    "dedupe_lines": ["A\nB\nA"],
    "text_counts": ["Робота робота — текст."],
    "phone_cleanup": ["0673333333\n+48501122334\nbogus"],
    "csv_unique": ["id;price\n1;50\n1;50"],
    "csv_summary": ["section;value\nA;12\nA;18\nB;20", "section", "value"],
    "csv_merge": ["id;price\n1;90", "id;stock\n1;12\n2;7"],
    "csv_compare": ["id;price\n1;90\n2;12", "id;price\n1;100\n3;50"],
    "checklist_progress": ["[x] Invoice\n[ ] Delivery"],
    "date_intervals": ["2026-11-26\n2026-12-01\n2026-12-04"],
    "rank_options": ["option;score;weight\nA;9;2\nB;7;1\nA;7;1"],
    "shift_plan": ["Аня\nМарко", "2026-11-26", "8", "yes"],
    "service_slots": ["2026-11-26", "09:30", "11:35", "30", "5"],
    "receipt_split": ["100.00", "Аня\nМарко\nЮлія"],
    "utm_builder": ["https://safeorbit.com.pl/?v=1&utm_source=old#solutions", "catalog", "web", "launch", ""],
}


async def login(client, username):
    await client.get("/login")
    result = await post(client, "/login", {"username": username, "password": "correct horse battery staple"})
    assert result.status_code == 303 and result.headers["location"] in {"/admin", "/workspace"}


def test_all_100_catalog_entries_and_through_the_app_each_of_the_74_new_tools():
    async def scenario():
        async with test_app() as (owner, standard, sessions):
            await seed(sessions)
            await login(owner, "+380672222222")
            layout = await owner.get("/workspace")
            assert len(MODULES) == 100 and len(WORKFLOWS) == 74
            assert layout.text.count("data-arrange-row ") == 100
            assert len({item.label for item in MODULES.values()}) == 100
            await login(standard, "+380671111111")
            assert (await standard.get("/workspace/tools/sale_margin")).status_code == 404
            for key, spec in WORKFLOWS.items():
                path = f"/workspace/tools/{key}"
                if spec.mode == "register":
                    choices = {"number": "50.25", "signed": "-4.75", "date": "2026-11-26",
                               "url": "https://safeorbit.com.pl", "long": "Extended entry", "text": "Sample record"}
                    values = [choices[field.kind] for field in spec.fields]
                elif spec.mode == "transform":
                    values = TRANSFORM_EXAMPLES[key]
                else:
                    values = ["10"] * len(spec.fields)
                    if key == "break_even":
                        values = ["500", "100", "40"]
                    if key == "sale_margin":
                        values = ["100", "75"]
                params = {f"f_{field.key}": value for field, value in zip(spec.fields, values, strict=True)}
                if spec.statuses:
                    params["state"] = spec.statuses[0]
                initial = await owner.get(path)
                assert initial.status_code == 200 and spec.label in initial.text, key
                created = await post(owner, path, {"title": f"Verified {key}", **params})
                assert created.status_code == 303, (key, created.status_code, created.text[:500])
                result = await owner.get(created.headers["location"])
                assert result.status_code == 200 and f"Verified {key}" in result.text, key
                record_id = created.headers["location"].split("#record-")[1]
                export = path + (f"/records/{record_id}/export" if spec.mode == "transform" else "/export")
                output = await owner.get(export)
                assert output.status_code == 200 and output.headers["content-type"].startswith("text/csv"), key
            async with sessions() as db:
                saved = dict((await db.execute(select(WorkspaceRecord.module, WorkspaceRecord.data))).all())
                assert json.loads(saved["sale_margin"])["answer"] == "25.00"
                assert json.loads(saved["break_even"])["answer"] == "9.00"
                assert json.loads(saved["service_slots"])["result"]["rows"][0][1:] == ["09:30", "10:00"]
                parts = json.loads(saved["receipt_split"])["result"]["rows"]
                assert sum(Decimal(part[1]) for part in parts) == 100
                assert "utm_source=catalog" in json.loads(saved["utm_builder"])["result"]["link"]
    asyncio.run(scenario())


def test_workflow_edit_filter_total_delete_and_cross_tenant_access():
    async def scenario():
        async with test_app() as (owner, stranger, sessions):
            await seed(sessions)
            await login(owner, "+380672222222")
            path = "/workspace/tools/expenses"
            form = {"title": "Monthly materials", "f_0": "Supplies", "f_1": "Supplier", "f_2": "75.25",
                    "f_3": "2026-11-26", "state": "Заплановано"}
            created = await post(owner, path, form)
            result = created.headers["location"]
            oid = result.split("#record-")[1]
            changed = await post(owner, path, {**form, "f_2": "149", "state": "Сплачено", "record_id": oid})
            assert changed.status_code == 303
            filtered_page = await owner.get(path, params={"state": "Сплачено", "q": "materials"})
            assert "149.00" in filtered_page.text
            assert "Monthly materials" not in (await owner.get(path, params={"q": "different"})).text
            assert (await post(owner, "/workspace/tools/sale_margin", {"title": "Bad", "f_0": "0", "f_1": "20"})).status_code == 422
            async with sessions() as db:
                (await db.get(Business, 1)).plan_type = "custom"
                await db.commit()
            await login(stranger, "+380671111111")
            assert (await stranger.get(path)).status_code == 200
            assert (await stranger.get(path + "/records/" + oid + "/edit")).status_code == 404
            assert (await post(owner, path + "/records/" + oid + "/delete", {})).status_code == 303
            assert "Monthly materials" not in (await owner.get(path)).text
    asyncio.run(scenario())
