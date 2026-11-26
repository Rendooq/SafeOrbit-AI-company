"""Bounded data transforms that work on the content entered in the workspace."""
import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from services.marketplace import normalize_phone
from services.workspace_tools import ToolError, amount, report, table, website_url


def lines(value, limit=1000):
    rows = [line.strip() for line in value.splitlines() if line.strip()]
    if not 1 <= len(rows) <= limit:
        raise ToolError(f"Введіть від 1 до {limit} рядків.")
    return rows


def unique_lines(data):
    original = lines(data[0])
    counts = defaultdict(int)
    for line in original:
        counts[line] += 1
    return report(["Рядок", "Повторів вилучено"], [(line, count - 1) for line, count in counts.items()],
                  f"Залишилось {len(counts)} із {len(original)} рядків.")


def text_counts(data):
    raw = data[0]
    words = re.findall(r"\b[^\W_]+(?:['’ʼ-][^\W_]+)*\b", raw, flags=re.UNICODE)
    counts = defaultdict(int)
    for word in words:
        counts[word.casefold()] += 1
    most_used = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:20]
    return report(["Слово", "Входжень"], most_used, f"Слів: {len(words)}. Символів із пробілами: {len(raw)}. Рядків: {len(raw.splitlines())}.")


def clean_phones(data):
    result = [(raw, normalize_phone(raw) or "Не розпізнано") for raw in lines(data[0])]
    valid = {phone for _, phone in result if phone.startswith("+")}
    return report(["Вхідний номер", "Формат E.164"], result, f"Унікальних розпізнаних номерів: {len(valid)}.")


def grid(text):
    source = text.lstrip("\ufeff").strip()
    if not source:
        raise ToolError("Додайте вхідну таблицю.")
    delimiter = max((";", "\t", ","), key=source.splitlines()[0].count)
    rows = [tuple(cell.strip() for cell in row) for row in csv.reader(io.StringIO(source), delimiter=delimiter) if any(row)]
    if not 2 <= len(rows) <= 1001 or not 1 <= len(rows[0]) <= 24:
        raise ToolError("Очікується заголовок і до 1000 рядків та 24 стовпців.")
    if any(len(row) != len(rows[0]) or any(len(cell) > 500 for cell in row) for row in rows):
        raise ToolError("Рядки таблиці мають бути однакової ширини, значення — до 500 символів.")
    if len(set(rows[0])) != len(rows[0]) or not all(rows[0]):
        raise ToolError("Заголовки мають бути непорожніми й унікальними.")
    return rows[0], rows[1:]


def csv_unique(data):
    headers, rows = grid(data[0])
    unique = list(dict.fromkeys(rows))
    return report(headers, unique, f"Вилучено {len(rows) - len(unique)} повністю однакових рядків.")


def csv_summary(data):
    headers, rows = grid(data[0])
    if data[1] not in headers or data[2] not in headers:
        raise ToolError("Вкажіть назви стовпців так, як у заголовку.")
    grouping, values = headers.index(data[1]), headers.index(data[2])
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[grouping]].append(amount(row[values], minimum=-1000000000))
    result = [(group, len(values), f"{sum(values):.2f}", f"{sum(values)/len(values):.2f}") for group, values in sorted(grouped.items())]
    return report([headers[grouping], "Кількість", "Сума", "Середнє"], result, f"Груп: {len(result)}. Рядків: {len(rows)}.")


def tables_by_key(data):
    left_headers, left = grid(data[0])
    right_headers, right = grid(data[1])
    if left_headers[0] != right_headers[0]:
        raise ToolError("Заголовки першого стовпця мають збігатися.")
    for rows in (left, right):
        keys = [row[0] for row in rows]
        if not all(keys) or len(keys) != len(set(keys)):
            raise ToolError("Перший стовпець має містити унікальні непорожні ключі.")
    return left_headers, {row[0]: row[1:] for row in left}, right_headers, {row[0]: row[1:] for row in right}


def csv_merge(data):
    first, left, second, right = tables_by_key(data)
    keys = sorted(left.keys() | right.keys())
    rows = [(key, *left.get(key, ("",) * (len(first)-1)), *right.get(key, ("",) * (len(second)-1))) for key in keys]
    return report([first[0], *[f"A · {x}" for x in first[1:]], *[f"B · {x}" for x in second[1:]]],
                  rows, f"Об’єднано {len(keys)} ключів.")


def csv_compare(data):
    first, left, second, right = tables_by_key(data)
    if first != second:
        raise ToolError("Для порівняння заголовки мають збігатися.")
    differences = []
    for key in sorted(left.keys() | right.keys()):
        if key not in left:
            differences.append((key, "Додано", "", "", ""))
        elif key not in right:
            differences.append((key, "Вилучено", "", "", ""))
        else:
            differences.extend((key, "Змінено", name, old, new)
                               for name, old, new in zip(first[1:], left[key], right[key]) if old != new)
    if len(differences) > 4000:
        raise ToolError("Забагато відмінностей. Поділіть файли на менші частини.")
    return report([first[0], "Зміна", "Стовпець", "Було", "Стало"], differences, f"Відмінностей: {len(differences)}.")


def checklist_progress(data):
    result = []
    for line in lines(data[0]):
        match = re.fullmatch(r"(?:-\s*)?\[([xX ])\]\s+(.+)", line)
        if not match:
            raise ToolError("Почніть кожен пункт з [x] або [ ].")
        result.append((match[2], "Виконано" if match[1].lower() == "x" else "Залишилось"))
    count = sum(status == "Виконано" for _, status in result)
    return report(["Пункт", "Статус"], result, f"Виконано {count}/{len(result)} ({100*count/len(result):.1f}%).")


def date_intervals(data):
    values = sorted(set(date.fromisoformat(value) for value in lines(data[0])))
    if len(values) < 2:
        raise ToolError("Введіть хоча б дві різні дати.")
    rows = [(start.isoformat(), end.isoformat(), (end-start).days) for start, end in zip(values, values[1:])]
    return report(["Від", "До", "Різниця, дні"], rows, f"Проміжків: {len(rows)}. Усього днів: {(values[-1]-values[0]).days}.")


def rank_options(data):
    rows = [(option, score, weight) for option, score, weight in table(data[0], ("option", "score", "weight"))]
    totals = defaultdict(lambda: [0, 0])
    for option, score, weight in rows:
        multiplier = amount(weight)
        totals[option][0] += amount(score, maximum=100) * multiplier
        totals[option][1] += multiplier
    if any(weight == 0 for _, weight in totals.values()):
        raise ToolError("Кожен варіант має містити хоча б одну ненульову вагу.")
    ranking = sorted(((option, total/weight) for option, (total, weight) in totals.items()), key=lambda item: (-item[1], item[0]))
    return report(["Варіант", "Зважений бал"], [(option, f"{score:.2f}") for option, score in ranking],
                  f"Оцінено варіантів: {len(ranking)}.")


def shift_plan(data):
    staff = list(dict.fromkeys(lines(data[0], 60)))
    start = date.fromisoformat(data[1])
    count = int(data[2])
    if data[2] != count or not 1 <= count <= 366:
        raise ToolError("Тривалість плану має бути від 1 до 366 днів.")
    rows = []
    for offset in range(count):
        day = start + timedelta(days=offset)
        if data[3] == "yes" and day.weekday() >= 5:
            continue
        rows.append((day.isoformat(), staff[len(rows) % len(staff)]))
    return report(["День", "Чергує"], rows, f"Заплановано змін: {len(rows)}.")


def service_slots(data):
    day = date.fromisoformat(data[0])
    start, end = (datetime.combine(day, time.fromisoformat(value)) for value in data[1:3])
    duration, pause = data[3:5]
    if not 5 <= duration <= 720 or not 0 <= pause <= 180 or end <= start:
        raise ToolError("Перевірте години, тривалість і перерву.")
    length, block = timedelta(minutes=float(duration)), timedelta(minutes=float(duration + pause))
    rows = []
    while start + length <= end:
        rows.append((day.isoformat(), start.strftime("%H:%M"), (start+length).strftime("%H:%M")))
        start += block
    return report(["День", "Початок", "Кінець"], rows, f"Можливих слотів: {len(rows)}.")


def receipt_split(data):
    people = list(dict.fromkeys(lines(data[1], 100)))
    cents = int(data[0] * 100)
    part, remainder = divmod(cents, len(people))
    rows = [(person, f"{(part + (index < remainder))/100:.2f}") for index, person in enumerate(people)]
    return report(["Учасник", "До сплати"], rows, f"Розподілено {data[0]:.2f} між {len(people)} учасниками.")


def utm_builder(data):
    raw, source, medium, campaign, content = data
    url = urlsplit(website_url(raw))
    tags = {"utm_source": source, "utm_medium": medium, "utm_campaign": campaign, "utm_content": content}
    original = [(key, val) for key, val in parse_qsl(url.query, keep_blank_values=True) if key not in tags]
    query = urlencode(original + [(key, value) for key, value in tags.items() if value])
    result = urlunsplit(url._replace(query=query))
    return report(["Посилання"], [(result,)], "Готове посилання для копіювання.", link=result)
