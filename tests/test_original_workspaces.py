import asyncio
import io
import re
import wave
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree

from pypdf import PdfWriter
from sqlalchemy import select

from test_platform import csrf, post, seed, test_app
from models import Business
from models_platform import WorkspaceRecord
from services import workspace_tools


async def sign_in(owner):
    await owner.get("/login")
    response = await post(owner, "/login", {"username": "+380672222222", "password": "correct horse battery staple"})
    assert response.headers["location"] == "/workspace"


def pdf_file():
    writer = PdfWriter()
    writer.add_blank_page(width=595.2756, height=841.8898)
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


def test_operational_tools_normalize_and_report_real_data():
    result = workspace_tools.reconcile("ttn;amount\n10001;300\n10002;100", "ttn;amount\n10001;290\n10003;40")
    assert dict(result["metrics"])["Очікувані виплати"] == "400.00 грн"
    assert dict(result["metrics"])["Фактично отримано"] == "330.00 грн"
    invoices = workspace_tools.invoices("item;unit;package;price;ordered\nCoffee;g;250;100;500\nTea;kg;1;300;1",
                                         "item;unit;package;price;ordered\nCoffee;kg;0.5;225;3")
    assert invoices["rows"][0] == ["Coffee", "kg", "400.00", "450.00", "+12.5%", "150.00"]
    assert invoices["rows"][1][4] == "Відсутня в поточній накладній"
    cut = workspace_tools.cutting("part;width;height;qty;rotate\nPanel;45;55;2;0", "100", "120", "3",
                                 "width;height;qty\n45;55;1")
    assert cut["boards"] == {"1": {"width": 45.0, "height": 55.0, "offcut": True},
                             "2": {"width": 100.0, "height": 120.0, "offcut": False}}


def test_saved_feed_copy_and_public_print_profile():
    async def scenario():
        async with test_app() as (owner, customer, sessions):
            await seed(sessions)
            await sign_in(owner)
            base = "/workspace/module/feeds"
            created = await post(owner, base, {"title": "Feed report", "repair": "yes",
                "first": "<rss><channel><item><id>123</id><price>150,0 UAH</price></item></channel></rss>",
                "second": "id;price;availability\n123;170 UAH;in_stock"})
            assert created.status_code == 303
            report = await owner.get(base)
            path = re.search(r'href="(/workspace/attachments/\d+)">google-shopping-corrected.xml', report.text)[1]
            assert (await customer.get(path)).status_code == 403
            attachment = await owner.get(path)
            assert attachment.headers["content-disposition"].startswith("attachment")
            field_values = {field.tag.rsplit("}", 1)[-1]: field.text for field in ElementTree.fromstring(attachment.content).find("./channel/item")}
            assert field_values == {"id": "123", "price": "170.00 UAH", "availability": "in_stock"}

            profile = await post(owner, "/workspace/preflight/profiles",
                                 {"title": "A4 poster", "width": "210", "height": "297", "bleed": "0", "dpi": "300"})
            assert profile.status_code == 303
            module = await owner.get("/workspace/module/preflight")
            public_path = re.search(r'href="(/maket/(\d+)/[A-Za-z0-9_-]+)"', module.text)
            link = public_path[1]
            assert (await customer.get(link + "x")).status_code == 404
            assert "A4 poster" in (await customer.get(link)).text
            files = {"file": ("poster.pdf", pdf_file(), "application/pdf")}
            assert (await customer.post(link, files=files)).status_code == 403
            output = await customer.post(link, files=files, headers=csrf(customer))
            assert output.status_code == 200 and "Перевірені параметри в нормі" in output.text
            assert (await post(owner, f"/workspace/records/{public_path[2]}/delete", {})).status_code == 303
            assert (await customer.get(link)).status_code == 404

    asyncio.run(scenario())


def test_tender_revisions_project_totals_and_car_comparison():
    async def scenario():
        async with test_app() as (owner, customer, sessions):
            await seed(sessions)
            await sign_in(owner)
            response = await post(owner, "/workspace/module/extras", {
                "title": "Additional paint", "project": "Project Blue", "first": "item;cost\nPaint;325", "days": "2"})
            page = await owner.get(response.headers["location"])
            proposal = re.search(r'href="(/proposals/[^"]+)"', page.text)[1]
            assert "Project Blue" in (await customer.get(proposal)).text
            assert (await post(customer, proposal, {"name": "Customer", "action": "approved"})).status_code == 303
            page = await owner.get("/workspace/module/extras")
            assert "325.00 грн" in page.text and "Погоджені допроботи за об’єктами" in page.text

            path = "/workspace/module/tender"
            word = "hello"
            from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
            writer = PdfWriter()
            page = writer.add_blank_page(200, 200)
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 25 25 Td (hello) Tj ET")
            page[NameObject("/Contents")] = writer._add_object(stream)
            content = io.BytesIO()
            writer.write(content)
            snapshot = {"id": "a" * 32, "code": "UA-2026-11-20-000001-a",
                        "title": "Tender", "source": "https://prozorro.gov.ua/tender/UA-2026-11-20-000001-a",
                        "date": "2026-11-20", "documents": {"1": ("Old.pdf", "2026-11-20")}}
            updated = {**snapshot, "date": "2026-11-21", "documents": {"1": ("Revised.pdf", "2026-11-21")}}
            with patch("routers.workspace.prozorro.tender_snapshot", AsyncMock(side_effect=[snapshot, updated])):
                for title in ("Initial", "Revised"):
                    response = await owner.post(path, data={"title": title, "body": word, "prozorro": "a" * 32},
                        files={"file": ("bid.pdf", content.getvalue(), "application/pdf")}, headers=csrf(owner))
                    assert response.status_code == 303, response.text
            tender = await owner.get(path)
            assert "Оновлено · Revised.pdf" in tender.text and snapshot["code"] in tender.text

            car_path = "/workspace/module/cars"
            cars = await post(owner, car_path, {"title": "Car shortlist", "car_priority": "mileage",
                "car_url_1": "https://www.otomoto.pl/one", "car_model_1": "First car", "car_year_1": "2021",
                "car_km_1": "85000", "car_price_1": "42000",
                "car_url_2": "https://www.otomoto.pl/two", "car_model_2": "Second car", "car_year_2": "2020",
                "car_km_2": "50000", "car_price_2": "45000"})
            assert cars.status_code == 303
            page = await owner.get(car_path)
            assert page.text.index("Second car") < page.text.index("First car")

    asyncio.run(scenario())


def test_checkout_notifies_only_on_status_changes_and_book_transcribes_on_request():
    async def scenario():
        async with test_app() as (owner, reporter, sessions):
            await seed(sessions)
            async with sessions() as db:
                business = await db.get(Business, 2)
                business.telegram_notifications_enabled = True
                business.telegram_notification_chat_id = "12345"
                business.telegram_token = "isolated"
                await db.commit()
            await sign_in(owner)
            created = await post(owner, "/workspace/probes", {"domain": "example.com"})
            key = re.search(r'class="secret" data-no-translate>([A-Za-z0-9_-]+)', created.text)[1]
            path = re.search(r'https://safeorbit.com.pl(/signals/checkout/\d+)', created.text)[1]
            with patch("routers.workspace.send_checkout_alert", AsyncMock()) as alert:
                for status in ("failed", "failed", "ok"):
                    result = await reporter.post(path, json={"status": status, "url": "https://example.com",
                        "step": "Basket", "ms": 150}, headers={"Authorization": f"Bearer {key}"})
                    assert result.status_code == 204
                    async with sessions() as db:
                        newest = await db.scalar(select(WorkspaceRecord).where(WorkspaceRecord.module == "checkout")
                                                 .order_by(WorkspaceRecord.id.desc()))
                        newest.created_at -= timedelta(minutes=2)
                        await db.commit()
                assert [call.args[-1] for call in alert.await_args_list] == ["failed", "ok"]

            audio = io.BytesIO()
            with wave.open(audio, "wb") as recording:
                recording.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                recording.writeframes(b"\0" * 1600)
            path = "/workspace/module/book"
            created = await owner.post(path, data={"title": "Audio chapter"},
                files={"file": ("chapter.wav", audio.getvalue(), "audio/wav")}, headers=csrf(owner))
            record_id = created.headers["location"].split("#record-")[1]
            with patch.dict("os.environ", {"WORKSPACE_TRANSCRIPTION_KEY": "", "GROQ_API_KEY": "local-test-key"}):
                assert "Розпізнати голос" in (await owner.get(path)).text
                import httpx
                client = httpx.AsyncClient
                transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"text": "Запис родини"}))
                with patch("routers.workspace.httpx.AsyncClient", lambda **kwargs: client(transport=transport)):
                    transcribed = await post(owner, f"/workspace/records/{record_id}/transcribe", {})
                assert transcribed.status_code == 303 and "Запис родини" in (await owner.get(path)).text

    asyncio.run(scenario())
