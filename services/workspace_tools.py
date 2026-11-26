"""Local, deterministic tools. Input documents are never sent to a third party."""
import csv
import io
import math
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree as SafeXML
from defusedxml.common import DefusedXmlException


class ToolError(ValueError):
    pass


def amount(value, *, minimum=Decimal("0"), maximum=Decimal("1000000000")):
    try:
        parsed = Decimal(str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ToolError("Введіть коректне число.") from exc
    if not parsed.is_finite() or not minimum <= parsed <= maximum:
        raise ToolError("Число поза дозволеним діапазоном.")
    return parsed.quantize(Decimal(".01"))


def printable(value):
    return f"{value:.2f}"


def table(text, columns):
    source = text.strip().lstrip("\ufeff")
    if not source:
        raise ToolError("Додайте таблицю з даними.")
    first_line = source.splitlines()[0]
    delimiter = max((";", "\t", ","), key=first_line.count)
    reader = csv.reader(io.StringIO(source), delimiter=delimiter)
    result = []
    header = next(reader, [])
    if tuple(s.strip().casefold() for s in header) != tuple(columns):
        raise ToolError("Очікувані заголовки: " + ", ".join(columns))
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(columns) or len(result) >= 5000 or any(len(cell) > 500 for cell in row):
            raise ToolError("Перевірте стовпці та обмежте таблицю 5000 рядками.")
        result.append(tuple(cell.strip() for cell in row))
    if not result:
        raise ToolError("У таблиці немає жодного рядка даних.")
    return result


def report(headers, rows, summary, **extra):
    return {"headers": headers, "rows": rows, "summary": summary, **extra}


TRACKING_FIELDS = {"ttn", "ттн", "номер ттн", "номер ен", "експрес накладна", "номер експрес накладної", "номер відправлення"}
AMOUNT_FIELDS = {"amount", "сума", "післяплата", "сума післяплати", "сума виплати", "сума платежу", "сума зарахування"}


def ledger_rows(source):
    if not source.strip():
        raise ToolError("Додайте реєстр або таблицю з ТТН і сумами.")
    first_lines = "\n".join(source.splitlines()[:8])
    preferred = max((";", "\t", ","), key=first_lines.count)
    for separator in dict.fromkeys((preferred, ";", "\t", ",")):
        parsed = list(csv.reader(io.StringIO(source.strip().lstrip("\ufeff")), delimiter=separator))
        for index, row in enumerate(parsed[:10]):
            headers = {re.sub(r"[^\w]+", " ", part.casefold()).strip(): col for col, part in enumerate(row)}
            tracking = next((col for value, col in headers.items() if value in TRACKING_FIELDS), None)
            total = next((col for value, col in headers.items() if value in AMOUNT_FIELDS), None)
            if tracking is None or total is None:
                continue
            lines = list((line[tracking].strip(), line[total].strip()) for line in parsed[index + 1:]
                         if len(line) > max(tracking, total) and line[tracking].strip()
                         and line[tracking].strip().casefold() not in {"разом", "всього", "підсумок", "total"})
            if not 1 <= len(lines) <= 5000:
                raise ToolError("У реєстрі має бути від 1 до 5000 записів.")
            return lines
    raise ToolError("Не знайдено стовпці «ТТН» і «Сума» (або ttn та amount).")


def workbook_csv(raw):
    from openpyxl import load_workbook
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            metadata = archive.infolist()
            if len(metadata) > 200 or sum(item.file_size for item in metadata) > 12 * 1024 * 1024:
                raise ToolError("Завантажте меншу таблицю Excel.")
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
    except ToolError:
        raise
    except (BadZipFile, ValueError, OSError, KeyError) as exc:
        raise ToolError("Не вдалося прочитати файл Excel.") from exc
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    try:
        sheet = workbook.active
        if sheet is None or (sheet.max_column or 0) > 100 or (sheet.max_row or 0) > 5010:
            raise ToolError("Перевірте розмір таблиці Excel.")
        for index, row in enumerate(sheet.iter_rows(max_col=sheet.max_column or 100, values_only=True)):
            if index >= 5010:
                raise ToolError("У реєстрі забагато рядків.")
            writer.writerow(row)
    finally:
        workbook.close()
    return output.getvalue()


def reconcile(expected, paid):
    def group(source):
        totals = defaultdict(lambda: Decimal("0"))
        counts = defaultdict(int)
        for tracking, raw in ledger_rows(source):
            tracking = tracking.replace(" ", "").replace("-", "")
            if not re.fullmatch(r"[0-9]{5,24}", tracking):
                raise ToolError("ТТН має містити від 5 до 24 цифр.")
            totals[tracking] += amount(re.sub(r"\s*(?:грн\.?|uah|₴)\s*$", "", raw, flags=re.IGNORECASE))
            counts[tracking] += 1
        return totals, counts
    left, left_counts = group(expected)
    right, right_counts = group(paid)
    rows = []
    for tracking in sorted(left.keys() | right.keys()):
        due, received = left.get(tracking, Decimal(0)), right.get(tracking, Decimal(0))
        flags = []
        if tracking not in left:
            flags.append("Немає відправлення")
        if tracking not in right:
            flags.append("Немає виплати")
        if tracking in left and tracking in right and due != received:
            flags.append("Суми різняться")
        if left_counts[tracking] > 1 or right_counts[tracking] > 1:
            flags.append("Повторювана ТТН")
        if flags:
            rows.append([tracking, printable(due), printable(received), printable(due - received), ", ".join(flags)])
    difference = sum(left.values()) - sum(right.values())
    return report(["ТТН", "Очікувалось", "Перераховано", "Різниця", "Що перевірити"], rows,
                  f"Унікальних ТТН: {len(left.keys() | right.keys())}. З розбіжностями: {len(rows)}. Різниця сум: {difference:.2f} грн.",
                  metrics=[("Очікувані виплати", f"{sum(left.values()):.2f} грн"),
                           ("Фактично отримано", f"{sum(right.values()):.2f} грн"),
                           ("Відправлення без виплат", str(len(left.keys() - right.keys()))),
                           ("Виплати без відправлень", str(len(right.keys() - left.keys())))])


def invoices(previous, current):
    units = {"kg": ("kg", 1), "g": ("kg", 1000), "l": ("l", 1), "ml": ("l", 1000), "pcs": ("pcs", 1)}

    def rates(source):
        values = {}
        for name, unit, package, price, ordered in table(source, ("item", "unit", "package", "price", "ordered")):
            if not name or unit.casefold() not in units:
                raise ToolError("Вкажіть назву й одиницю: kg, g, l, ml або pcs.")
            base, scale = units[unit.casefold()]
            key = (name.casefold(), base)
            if key in values:
                raise ToolError("Позиції мають бути унікальні після перерахунку одиниць.")
            values[key] = (name, amount(price) * scale / amount(package, minimum=Decimal(".01")), amount(ordered) / scale)
        return values
    old, new = rates(previous), rates(current)
    rows = []
    total = Decimal(0)
    for key, (name, current_rate, quantity) in new.items():
        unit = key[1]
        if key not in old:
            rows.append([name, unit, "—", printable(current_rate), "Нова позиція", "—"])
            continue
        previous_rate = old[key][1]
        delta = (current_rate - previous_rate) * quantity
        total += delta
        percent = f"{(current_rate / previous_rate - 1) * 100:+.1f}%" if previous_rate else "—"
        rows.append([name, unit, printable(previous_rate), printable(current_rate), percent, printable(delta)])
    for key in old.keys() - new.keys():
        name, previous_rate, _ = old[key]
        rows.append([name, key[1], printable(previous_rate), "—", "Відсутня в поточній накладній", "—"])
    return report(["Позиція", "Од.", "Було / од.", "Стало / од.", "Зміна", "За закуплену кількість"], rows,
                  f"Зміна витрат за порівнюваними позиціями: {total:+.2f} грн.")


def website_url(text):
    try:
        value = urlsplit(text)
        valid = (value.scheme in {"http", "https"} and value.hostname and "." in value.hostname
                 and not value.username and not value.password and not any(ch.isspace() for ch in text))
    except ValueError:
        valid = False
    if not valid:
        raise ToolError("Вкажіть повне посилання http:// або https://.")
    return text


def feeds(raw, comparison="", repair=False):
    try:
        root = SafeXML.fromstring(raw)
    except (ElementTree.ParseError, DefusedXmlException, ValueError) as exc:
        raise ToolError("Не вдалося безпечно прочитати XML.") from exc
    local = lambda tag: tag.rsplit("}", 1)[-1]
    items = list(item for item in root.iter() if local(item.tag) in ("item", "entry"))
    if not items or len(items) > 5000:
        raise ToolError("Фід має містити від 1 до 5000 товарів у форматі RSS або Atom.")
    rows = []
    ids = set()
    availability_values = {"in_stock", "out_of_stock", "preorder", "backorder"}
    price_pattern = re.compile(r"([0-9]+(?:[.,][0-9]{1,2})?)\s+([A-Z]{3})")

    def normalized_price(price):
        found = price_pattern.fullmatch(price)
        return f"{amount(found[1]):.2f} {found[2]}" if found else ""

    reference = {}
    if comparison.strip():
        for key, price, availability in table(comparison, ("id", "price", "availability")):
            price = normalized_price(price)
            if not key or key in reference or not price or availability not in availability_values:
                raise ToolError("Перевірте унікальні ID, ціни з валютою та наявність у контрольній таблиці.")
            reference[key] = (price, availability)
    required = {"id", "title", "description", "link", "image_link", "availability", "price"}
    changed = 0
    namespace = "{http://base.google.com/ns/1.0}"
    for index, item in enumerate(items, 1):
        elements = {local(el.tag): el for el in item}
        fields = {key: (el.text or el.get("href") or "").strip() for key, el in elements.items()}
        missing = sorted(key for key in required if not fields.get(key))
        errors = ["Відсутнє поле: " + key for key in missing]
        product_id = fields.get("id", "")
        if product_id:
            if product_id in ids:
                errors.append("Повторний id")
            ids.add(product_id)
        if fields.get("price") and not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})? [A-Z]{3}", fields["price"]):
            errors.append("Ціна має бути у форматі 199.00 UAH")
        if fields.get("availability") and fields["availability"] not in availability_values:
            errors.append("Некоректна доступність")
        if fields.get("condition") and fields["condition"] not in {"new", "refurbished", "used"}:
            errors.append("Некоректний стан товару")
        if product_id in reference:
            price, availability = reference[product_id]
            if normalized_price(fields.get("price", "")) != price or fields.get("availability") != availability:
                errors.append("Ціна або наявність не збігається з контрольною таблицею")
        for field in ("link", "image_link"):
            if fields.get(field):
                try:
                    website_url(fields[field])
                except ToolError:
                    errors.append(f"Некоректне посилання: {field}")
        if errors:
            rows.append([product_id[:100] or f"#{index}", fields.get("title", "")[:180], " · ".join(errors)])
        if repair:
            price, availability = reference.get(product_id, (normalized_price(fields.get("price", "")), ""))
            for field, value in (("price", price), ("availability", availability)):
                if not value or fields.get(field) == value:
                    continue
                element = elements.get(field)
                if element is None:
                    element = ElementTree.SubElement(item, namespace + field)
                element.text = value
                changed += 1
    rows.extend([key, "", "Товар із контрольної таблиці відсутній у фіді"] for key in reference.keys() - ids)
    summary = f"Товарів перевірено: {len(items)}. Зауваження: {len(rows)}."
    if repair:
        summary += f" Виправлено полів у копії XML: {changed}. Зауваження описують вхідний фід."
    return report(["ID", "Товар", "Виправити"], rows, summary,
                  **({"repaired_xml": ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)} if repair else {}))


def pdf_pages(data):
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 100:
            raise ToolError("Додайте PDF без пароля та з 1–100 сторінками.")
        return list(reader.pages)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError("Не вдалося прочитати цей PDF.") from exc


def tender(keywords, previous, raw):
    phrases = list(dict.fromkeys(s.strip() for s in keywords.splitlines() if s.strip()))
    old_phrases = set(s.strip() for s in previous.splitlines() if s.strip())
    if not phrases or len(phrases) > 80 or any(len(p) > 180 for p in phrases):
        raise ToolError("Введіть від 1 до 80 коротких вимог, кожну з нового рядка.")
    try:
        pages = [" ".join((page.extract_text() or "")[:100000].casefold().split()) for page in pdf_pages(raw)]
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError("Не вдалося витягнути текст із PDF.") from exc
    if not any(pages):
        raise ToolError("У PDF немає текстового шару. Додайте документ із текстом.")
    rows = []
    for phrase in phrases:
        needle = " ".join(phrase.casefold().split())
        matches = [str(i) for i, content in enumerate(pages, 1) if needle in content]
        rows.append([phrase, ", ".join(matches) or "Збігів немає", "Нова" if old_phrases and phrase not in old_phrases else ""])
    rows.extend([phrase, "—", "Вилучено зі списку"] for phrase in sorted(old_phrases - set(phrases))[:80])
    return report(["Вимога або фраза", "Сторінки PDF", "Зміни"], rows,
                  "Збіги фраз у документі. Підтвердьте відповідність вимогам за оригіналом.")


def image_resolutions(page):
    """Measure direct image XObjects in their placed dimensions on the page."""
    resources = page.get("/Resources")
    x_objects = resources.get_object().get("/XObject") if resources else None
    contents = page.get_contents()
    if x_objects is None or contents is None:
        return []
    images = x_objects.get_object()
    matrix = (1, 0, 0, 1)
    stack = []
    results = []
    for operands, operator in contents.operations:
        if operator == b"q":
            stack.append(matrix)
        elif operator == b"Q" and stack:
            matrix = stack.pop()
        elif operator == b"cm":
            a, b, c, d = map(float, operands[:4])
            x, y, u, v = matrix
            matrix = a*x+b*u, a*y+b*v, c*x+d*u, c*y+d*v
        elif operator == b"Do" and operands and operands[0] in images:
            image = images[operands[0]].get_object()
            if image.get("/Subtype") != "/Image":
                continue
            x, y, u, v = matrix
            w = math.hypot(x, y) * float(page.user_unit)
            h = math.hypot(u, v) * float(page.user_unit)
            if w > 0 and h > 0:
                result = min(72 * int(image["/Width"]) / w, 72 * int(image["/Height"]) / h)
                if math.isfinite(result):
                    results.append(round(result))
    return results


def print_settings(width, height, bleed, dpi="300"):
    width, height, bleed = map(amount, (width, height, bleed))
    dpi = int(amount(dpi or "300", minimum=36, maximum=1200))
    if not (0 < width <= 10000 and 0 < height <= 10000 and 0 <= bleed <= 100):
        raise ToolError("Вкажіть коректні розміри друку та вильоти в міліметрах.")
    return width, height, bleed, dpi


def preflight(raw, width, height, bleed, dpi="300"):
    width, height, bleed, dpi = print_settings(width, height, bleed, dpi)
    millimeters = Decimal("25.4") / 72
    rows = []
    for index, page in enumerate(pdf_pages(raw), 1):
        trim = page.trimbox
        bounds = page.bleedbox
        scale = millimeters * Decimal(str(page.user_unit))
        size = [Decimal(str(trim.width)) * scale, Decimal(str(trim.height)) * scale]
        if page.rotation % 180:
            size.reverse()
        actual = [trim.left - bounds.left, trim.bottom - bounds.bottom, bounds.right - trim.right, bounds.top - trim.top]
        available = min(Decimal(str(n)) * scale for n in actual)
        issues = []
        if abs(size[0] - width) > Decimal(".25") or abs(size[1] - height) > Decimal(".25"):
            issues.append("Розмір TrimBox відрізняється")
        if available + Decimal(".15") < bleed:
            issues.append("Недостатній виліт BleedBox")
        try:
            low = [ppi for ppi in image_resolutions(page) if ppi < dpi]
        except (OverflowError, ValueError, AttributeError, TypeError, KeyError):
            low = []
            issues.append("Не вдалося перевірити ресурси зображень")
        if low:
            issues.append(f"Зображень нижче {dpi} ppi: {len(low)} (мінімум {min(low)} ppi)")
        rows.append([index, f"{size[0]:.1f} × {size[1]:.1f}", f"{available:.1f}", " · ".join(issues) or "Перевірені параметри в нормі"])
    return report(["Сторінка", "Формат, мм", "Найменший виліт, мм", "Результат"], rows,
                  "Перевірено формат, вильоти та роздільність безпосередньо розміщених растрових зображень.")


def cutting(raw, width, height, kerf, offcuts=""):
    width, height, kerf = map(amount, (width, height, kerf))
    if not (0 < width <= 10000 and 0 < height <= 10000 and 0 <= kerf <= 30):
        raise ToolError("Перевірте розмір плити й ширину пропилу.")
    parts = []
    for name, w, h, qty, rotate in table(raw, ("part", "width", "height", "qty", "rotate")):
        w, h, count = amount(w), amount(h), amount(qty)
        if not name or min(w, h, count) <= 0 or count != int(count) or rotate not in {"0", "1"} or len(parts) + int(count) > 500:
            raise ToolError("Вкажіть від 1 до 500 деталей, цілу кількість та rotate 0 або 1.")
        parts.extend([(name, w, h, rotate == "1")] * int(count))
    parts.sort(key=lambda part: part[1] * part[2], reverse=True)
    boards, dimensions, rows = [], [], []
    if offcuts.strip():
        for offcut_width, offcut_height, count in table(offcuts, ("width", "height", "qty")):
            ow, oh, count = amount(offcut_width), amount(offcut_height), amount(count)
            if not (0 < ow <= 10000 and 0 < oh <= 10000 and count == int(count) and 0 < count <= 100 - len(boards)):
                raise ToolError("Укажіть до 100 залишків із коректними розмірами й цілою кількістю.")
            for _ in range(int(count)):
                boards.append([(Decimal(0), Decimal(0), ow, oh)])
                dimensions.append((ow, oh, True))
    for name, w, h, rotate in parts:
        options = [(w, h, False), (h, w, True)] if rotate and w != h else [(w, h, False)]
        positions = []
        for board_index, rectangles in enumerate(boards):
            for rect_index, (x, y, rw, rh) in enumerate(rectangles):
                for pw, ph, rotated in options:
                    if pw <= rw and ph <= rh:
                        positions.append((rw * rh - pw * ph, board_index, rect_index, pw, ph, rotated))
        if positions:
            _, board_index, rect_index, pw, ph, rotated = min(positions)
        else:
            choice = next(((pw, ph, turned) for pw, ph, turned in options if pw <= width and ph <= height), None)
            if choice is None:
                raise ToolError(f"Деталь «{name}» не поміщається на плиті.")
            pw, ph, rotated = choice
            board_index, rect_index = len(boards), 0
            boards.append([(Decimal(0), Decimal(0), width, height)])
            dimensions.append((width, height, False))
        x, y, rw, rh = boards[board_index].pop(rect_index)
        remaining = [(x + pw + kerf, y, rw - pw - kerf, ph), (x, y + ph + kerf, rw, rh - ph - kerf)]
        boards[board_index].extend(rect for rect in remaining if rect[2] > 0 and rect[3] > 0)
        rows.append([board_index + 1, name, printable(x), printable(y), printable(pw), printable(ph), "Так" if rotated else "Ні"])
    used_boards = {int(row[0]) for row in rows}
    area = sum(w * h for i, (w, h, _) in enumerate(dimensions, 1) if i in used_boards)
    used_percent = 100 * sum(part[1] * part[2] for part in parts) / area
    used_offcuts = sum(1 for i, (_, _, offcut) in enumerate(dimensions, 1) if offcut and i in used_boards)
    return report(["Плита", "Деталь", "X, мм", "Y, мм", "Ширина", "Висота", "Повернуто"], rows,
                  f"Плит: {len(used_boards)}. Залишків використано: {used_offcuts}. Деталей: {len(parts)}. Використано площі: {used_percent:.1f}%.",
                  board_width=float(width), board_height=float(height),
                  boards={str(i): {"width": float(w), "height": float(h), "offcut": offcut}
                          for i, (w, h, offcut) in enumerate(dimensions, 1) if i in used_boards})


def csv_report(headers, rows):
    out = io.StringIO()
    writer = csv.writer(out)
    def safe(value):
        return "'" + value if isinstance(value, str) and value.lstrip(" \n").startswith(("=", "+", "-", "@", "\t", "\r")) else value
    writer.writerow(map(safe, headers))
    writer.writerows(map(safe, row) for row in rows)
    return "\ufeff" + out.getvalue()
