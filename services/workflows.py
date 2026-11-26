"""Workflow schemas and calculations for the optional constructor modules."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable
from services import workflow_data as data
from services.workspace_tools import ToolError


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"
    required: bool = True


@dataclass(frozen=True)
class Workflow:
    label: str
    description: str
    group: str
    fields: tuple[Field, ...]
    mode: str
    output: str = ""
    operation: Callable | None = None
    statuses: tuple[str, ...] = ()
    aggregate: tuple[str, ...] = ()


def field(label, kind="text", required=True, key=""):
    return Field(key or label, label, kind, required)


def calc(label, desc, group, inputs, output, formula):
    return Workflow(label, desc, group, tuple(field(name, "number", key=str(i)) for i, name in enumerate(inputs)),
                    "calc", output, formula)


def register(label, desc, group, fields, statuses, totals=()):
    specs = tuple(field(name, kind, not optional, key=str(i))
                  for i, (name, kind, *optional) in enumerate(fields))
    return Workflow(label, desc, group, specs, "register", statuses=statuses, aggregate=tuple(str(i) for i in totals))


def transform(label, desc, fields, operation):
    return Workflow(label, desc, "Робота з даними", tuple(field(name, kind, required, key=str(i))
                    for i, (name, kind, required) in enumerate(fields)), "transform", operation=operation)


FINANCE = "Фінанси і продажі"
OPERATIONS = "Операції та закупівлі"
TEAM = "Команда і час"
QUALITY = "Виробництво та якість"
MARKETING = "Маркетинг і клієнти"
DEFAULT_STATUS = ("Новий", "У роботі", "Завершено")
MONEY_STATUS = ("Очікується", "Частково", "Оплачено")
JOB_STATUS = ("Заплановано", "У роботі", "Готово")


def ratio(numerator, denominator):
    if denominator <= 0:
        raise ToolError("Дільник має бути більшим за нуль.")
    return numerator / denominator


def ceil(value):
    return value.to_integral_value(rounding="ROUND_CEILING")


def bounded_percent(value):
    if not 0 <= value <= 100:
        raise ToolError("Відсоток має бути від 0 до 100.")
    return value / 100


def target_margin(cost, target):
    return ratio(cost, 1 - bounded_percent(target))


def compare_quotes(price_a, delivery_a, price_b, delivery_b):
    first, second = price_a + delivery_a, price_b + delivery_b
    preferred = "A" if first < second else "B" if second < first else "однакова ціна"
    return f"{preferred} · різниця {abs(first - second):.2f}"


CALCULATIONS = {
    "sale_margin": calc("Маржа продажу", "Валова маржа від ціни продажу.", FINANCE,
                        ("Ціна", "Собівартість"), "Маржа, %", lambda price, cost: 100 * ratio(price - cost, price)),
    "markup_target": calc("Ціна за цільовою маржею", "Мінімальна ціна для заданої маржі.", FINANCE,
                           ("Собівартість", "Цільова маржа, %"), "Ціна", target_margin),
    "break_even": calc("Точка беззбитковості", "Кількість продажів для покриття постійних витрат.", FINANCE,
                        ("Постійні витрати", "Ціна за одиницю", "Змінні витрати за одиницю"), "Одиниць", lambda fixed, price, unit: ceil(ratio(fixed, price - unit))),
    "order_cost": calc("Економіка замовлення", "Залишок після витрат на товар, комісію і доставку.", FINANCE,
                        ("Дохід", "Товар", "Доставка", "Комісія, %"), "Залишок", lambda income, goods, ship, fee: income * (1 - bounded_percent(fee)) - goods - ship),
    "ad_acquisition": calc("Вартість залучення", "Скільки коштував один новий клієнт з реклами.", MARKETING,
                            ("Рекламні витрати", "Нові клієнти"), "За клієнта", ratio),
    "average_ticket": calc("Середній чек", "Середній дохід з оплаченого замовлення.", FINANCE,
                           ("Виручка", "Оплачені замовлення"), "Середній чек", ratio),
    "mrr_growth": calc("Зростання регулярного доходу", "Зміна місячної підписної виручки.", FINANCE,
                         ("Попередній MRR", "Поточний MRR"), "Зміна, %", lambda old, new: 100 * ratio(new - old, old)),
    "churn_rate": calc("Відтік клієнтів", "Частка втрат від клієнтів на початок періоду.", FINANCE,
                         ("Втрачено клієнтів", "Клієнти на початок"), "Відтік, %", lambda lost, total: 100 * bounded_percent(100 * ratio(lost, total))),
    "renewal_target": calc("План продовжень", "Мінімальна кількість продовжень для цілі.", FINANCE,
                           ("Потрібна виручка", "Середня підписка"), "Продовжень", lambda goal, price: ceil(ratio(goal, price))),
    "stock_cover": calc("Запас у днях", "На скільки днів вистачить залишку.", OPERATIONS,
                        ("Одиниць у наявності", "Продано за день"), "Днів", ratio),
    "reorder_point": calc("Точка повторного замовлення", "Поріг залишку з урахуванням терміну доставки.", OPERATIONS,
                           ("Витрата на день", "Днів доставки", "Страховий запас"), "Одиниць", lambda use, days, safety: ceil(use * days + safety)),
    "purchase_batch": calc("Обсяг закупівлі", "Скільки докупити до цільового запасу.", OPERATIONS,
                            ("Цільовий запас", "На складі", "В дорозі"), "Замовити", lambda target, available, transit: max(0, ceil(target - available - transit))),
    "delivery_cost": calc("Собівартість доставки", "Частка витрат маршруту на одну посилку.", OPERATIONS,
                          ("Паливо", "Робота", "Інші витрати", "Посилки"), "За посилку", lambda fuel, work, other, orders: ratio(fuel + work + other, orders)),
    "distance_fuel": calc("Паливо на маршрут", "Розрахунок вартості пального за відстанню.", OPERATIONS,
                           ("Кілометрів", "Літрів на 100 км", "Ціна літра"), "Вартість", lambda km, liters, price: km * liters * price / 100),
    "capacity": calc("Пропускна здатність", "Скільки послуг уміститься в робочу зміну.", TEAM,
                      ("Людей", "Годин на людину", "Тривалість послуги, хв"), "Повних слотів", lambda people, hours, minutes: people * (ratio(hours * 60, minutes).to_integral_value(rounding="ROUND_FLOOR"))),
    "cost_per_hour": calc("Собівартість години", "Розподіл витрат за оплачуваними годинами.", TEAM,
                           ("Витрати", "Оплачувані години"), "За годину", ratio),
    "overtime_budget": calc("Бюджет понаднормових", "Додаткові витрати за введеним коефіцієнтом.", TEAM,
                            ("Години", "Ставка за годину", "Коефіцієнт"), "Вартість", lambda hours, rate, factor: hours * rate * factor),
    "lead_time": calc("Тривалість виконання", "Сумарний час виробництва, черги і доставки.", OPERATIONS,
                       ("Годин у черзі", "Годин виробництва", "Годин доставки"), "Годин", lambda a, b, c: a + b + c),
    "discount_check": calc("Ціна зі знижкою", "Остаточна сума після знижки.", FINANCE,
                            ("Початкова ціна", "Знижка, %"), "Ціна", lambda price, discount: price * (1 - bounded_percent(discount))),
    "tax_split": calc("Сума без податку", "Виділіть введену відсоткову ставку із загальної суми.", FINANCE,
                      ("Сума з податком", "Ставка, %"), "Сума без податку", lambda gross, tax: ratio(gross, 1 + bounded_percent(tax))),
    "installment": calc("Поділ платежу", "Рівна частина залишку після внеску.", FINANCE,
                         ("Сума", "Перший внесок", "Кількість частин"), "Сума частини", lambda total, down, count: ratio(max(Decimal(0), total - down), count)),
    "project_reserve": calc("Резерв проєкту", "Кошторис з відсотковим запасом.", FINANCE,
                             ("Кошторис", "Резерв, %"), "Кошторис із резервом", lambda estimate, reserve: estimate * (1 + bounded_percent(reserve))),
    "vendor_compare": calc("Порівняння двох постачальників", "Підсумок з доставкою для кожної пропозиції.", OPERATIONS,
                            ("Поставка A", "Доставка A", "Поставка B", "Доставка B"), "Вигідніше", compare_quotes),
    "currency_quote": calc("Перерахунок валюти", "Перерахуйте суму за введеним курсом і комісією.", FINANCE,
                            ("Сума", "Курс", "Комісія, %"), "Після комісії", lambda value, rate, fee: value * rate * (1 - bounded_percent(fee))),
    "portion_cost": calc("Собівартість порції", "Витрати інгредієнтів і паковання на одну порцію.", QUALITY,
                           ("Інгредієнти всього", "Кількість порцій", "Паковання на порцію"), "За порцію", lambda cost, count, package: ratio(cost, count) + package),
    "recipe_scale": calc("Масштабування рецепта", "Перерахуйте інгредієнт на іншу кількість порцій.", QUALITY,
                           ("Маса інгредієнта, г", "Початково порцій", "Потрібно порцій"), "Потрібно, г", lambda weight, old, new: ratio(weight * new, old)),
    "print_yield": calc("Тираж з урахуванням браку", "Скільки копій закласти під допустимі втрати.", QUALITY,
                          ("Придатних копій", "Очікуваний брак, %"), "Надрукувати", lambda copies, waste: ceil(ratio(copies, 1 - bounded_percent(waste)))),
    "area_material": calc("Матеріал за площею", "Урахуйте запас і площу одного паковання.", QUALITY,
                            ("М² поверхні", "М² у пакованні", "Запас, %"), "Паковань", lambda area, package, reserve: ceil(ratio(area * (1 + bounded_percent(reserve)), package))),
    "quote_variance": calc("Відхилення від кошторису", "Різниця між планом і фактичними витратами.", FINANCE,
                             ("Кошторис", "Фактично"), "Перевищення", lambda estimate, actual: actual - estimate),
    "rate_change": calc("Зміна погодинної ставки", "Нова ставка після підвищення.", TEAM,
                          ("Поточна ставка", "Підвищення, %"), "Нова ставка", lambda wage, increase: wage * (1 + bounded_percent(increase))),
}

REGISTERS = {
    "incoming_leads": register("Вхідні заявки", "Джерело, контакт, оцінка суми та наступний крок.", MARKETING,
        [("Контакт", "text"), ("Канал", "text"), ("Прогноз, грн", "number"), ("Наступний контакт", "date", True)], ("Нова", "Зв’язались", "Прийнято", "Відмова"), (2,)),
    "quotes": register("Комерційні пропозиції", "Дедлайни, суми й рішення замовників.", FINANCE,
        [("Замовник", "text"), ("Сума, грн", "number"), ("Діє до", "date"), ("Посилання", "url", True)], ("Чернетка", "Надіслано", "Погоджено", "Відхилено"), (1,)),
    "expenses": register("Реєстр витрат", "Статті, одержувачі й підтвердження витрат.", FINANCE,
        [("Стаття", "text"), ("Постачальник", "text"), ("Сума, грн", "number"), ("Дата витрати", "date")], ("Заплановано", "Сплачено", "Повернено"), (2,)),
    "receivables": register("Дебіторська заборгованість", "Платежі від замовників із датами погашення.", FINANCE,
        [("Платник", "text"), ("Номер рахунку", "text"), ("Залишок, грн", "number"), ("Строк", "date")], MONEY_STATUS, (2,)),
    "payables": register("Кредиторська заборгованість", "Ваші платежі перед постачальниками та підрядниками.", FINANCE,
        [("Одержувач", "text"), ("Рахунок", "text"), ("До сплати, грн", "number"), ("Строк платежу", "date")], MONEY_STATUS, (2,)),
    "purchase_orders": register("Замовлення постачальникам", "План доставки та приймання закупівель.", OPERATIONS,
        [("Постачальник", "text"), ("Номер замовлення", "text"), ("Вартість, грн", "number"), ("Очікується", "date")], ("Чернетка", "Замовлено", "Частково", "Прийнято"), (2,)),
    "supplier_cards": register("Оцінка постачальників", "Категорії, строки доставки й умови оплати.", OPERATIONS,
        [("Постачальник", "text"), ("Категорія", "text"), ("Термін доставки, днів", "number"), ("Умови оплати", "text")], ("На перевірці", "Погоджений", "Призупинений")),
    "goods_returns": register("Повернення товарів", "Причини, суми до повернення і підтвердження.", OPERATIONS,
        [("Номер замовлення", "text"), ("Причина", "text"), ("До повернення, грн", "number"), ("До дати", "date", True)], ("Запит", "Прийнято", "Компенсовано", "Відмовлено"), (2,)),
    "parcels": register("Посилки", "Канали доставки та контроль строків отримання.", OPERATIONS,
        [("ТТН", "text"), ("Перевізник", "text"), ("Очікувана дата", "date"), ("Вартість доставки, грн", "number", True)], ("Готується", "В дорозі", "Доставлено", "Повертається"), (3,)),
    "stock_adjustments": register("Коригування запасів", "Прихід, списання і зміни залишків за артикулом.", OPERATIONS,
        [("Артикул", "text"), ("Зміна кількості + / −", "signed"), ("Дата", "date"), ("Причина", "text")], ("На розгляді", "Проведено", "Скасовано"), (1,)),
    "inventory_counts": register("Інвентаризація", "Порівняння облікового і фактичного залишку.", OPERATIONS,
        [("Артикул", "text"), ("Обліковий залишок", "number"), ("Фактично", "number"), ("Дата підрахунку", "date")], ("Перерахувати", "Перевірено", "Виправлено"), (1, 2)),
    "equipment": register("Паспорт обладнання", "Інвентарні номери, місце й закупівельна вартість.", QUALITY,
        [("Інвентарний номер", "text"), ("Місце", "text"), ("Вартість, грн", "number"), ("Дата придбання", "date", True)], ("На складі", "В експлуатації", "У ремонті", "Списано"), (2,)),
    "maintenance": register("Техобслуговування", "Заплановані й виконані сервісні роботи.", QUALITY,
        [("Обладнання", "text"), ("Вид робіт", "text"), ("Дата ТО", "date"), ("Виконавець", "text", True)], JOB_STATUS),
    "defects": register("Контроль браку", "Партії, типи дефектів і забракована кількість.", QUALITY,
        [("Партія", "text"), ("Дефект", "text"), ("Забраковано, одиниць", "number"), ("Дата", "date")], ("Виявлено", "На аналізі", "Виправлено", "Списано"), (2,)),
    "incidents": register("Робочі інциденти", "Фіксація наслідків, відповідального та дій.", QUALITY,
        [("Місце", "text"), ("Дата", "date"), ("Наслідки", "long"), ("Відповідальний", "text")], ("Новий", "Розслідування", "Усунено")),
    "warranties": register("Гарантійні звернення", "Номер придбання, строк гарантії і рішення.", QUALITY,
        [("Номер придбання", "text"), ("Виріб", "text"), ("Гарантія до", "date"), ("Проблема", "long")], ("Нове", "На перевірці", "Ремонт", "Заміна", "Закрито")),
    "inspections": register("Перевірки якості", "Результати, відповідальний за виправлення і строк.", QUALITY,
        [("Об’єкт", "text"), ("Пройдено пунктів", "number"), ("Пунктів усього", "number"), ("Виправити до", "date", True)], ("Заплановано", "З зауваженнями", "Пройдено"), (1, 2)),
    "permits": register("Строки дозволів", "Дати закінчення й посилання на документи.", OPERATIONS,
        [("Документ", "text"), ("Номер", "text"), ("Діє до", "date"), ("Посилання", "url", True)], ("Дійсний", "На поновленні", "Закінчився")),
    "staff_shifts": register("Зміни команди", "Робочі місця, дати і тривалість змін.", TEAM,
        [("Працівник", "text"), ("Робоче місце", "text"), ("Дата зміни", "date"), ("Годин", "number")], ("Запланована", "Підтверджена", "Відпрацьована", "Скасована"), (3,)),
    "time_off": register("Відпустки", "Періоди відсутності й рішення щодо заяв.", TEAM,
        [("Працівник", "text"), ("Від", "date"), ("До", "date"), ("Робочих днів", "number")], ("Запит", "Погоджено", "Відмовлено"), (3,)),
    "hiring": register("Підбір персоналу", "Вакансії, кандидати й дати співбесід.", TEAM,
        [("Кандидат", "text"), ("Вакансія", "text"), ("Контакт", "text"), ("Співбесіда", "date", True)], ("Кандидат", "Співбесіда", "Пропозиція", "Найнято", "Відмова")),
    "training": register("Навчання команди", "Прогрес навчання і навантаження в годинах.", TEAM,
        [("Працівник", "text"), ("Курс", "text"), ("Годин", "number"), ("Завершити до", "date")], ("Заплановано", "Навчається", "Завершив"), (2,)),
    "campaigns": register("Рекламні кампанії", "Канали, бюджети й строки запуску.", MARKETING,
        [("Канал", "text"), ("Бюджет, грн", "number"), ("Дата запуску", "date"), ("Посилання", "url", True)], ("Чернетка", "Активна", "Зупинено", "Завершено"), (1,)),
    "content_calendar": register("Календар публікацій", "Теми, канали, дати та посилання на матеріали.", MARKETING,
        [("Тема", "text"), ("Майданчик", "text"), ("Дата публікації", "date"), ("Матеріал", "url", True)], ("Ідея", "Чернетка", "Готово", "Опубліковано")),
    "feedback_log": register("Звернення та відгуки", "Теми користувачів і строки відповіді.", MARKETING,
        [("Канал", "text"), ("Тема", "text"), ("Відповісти до", "date", True), ("Суть", "long")], ("Нове", "В опрацюванні", "Написали відповідь")),
    "procurement_bids": register("Календар тендерів", "Бюджети, посилання і дедлайни подання.", OPERATIONS,
        [("Ідентифікатор тендера", "text"), ("Подати до", "date"), ("Бюджет, грн", "number"), ("Посилання", "url", True)], ("Розглядаємо", "Готуємо", "Подано", "Завершено"), (2,)),
    "client_deliveries": register("Передача проєктів", "Результати роботи та підтвердження приймання.", OPERATIONS,
        [("Замовник", "text"), ("Дата передачі", "date"), ("Матеріали", "url", True), ("Відповідальний", "text")], ("Готується", "Передано", "Потрібні правки", "Прийнято")),
    "service_subscriptions": register("Підписки та ліцензії", "Суми, дати продовжень і стан підписок.", FINANCE,
        [("Сервіс", "text"), ("Сума за період, грн", "number"), ("Наступний платіж", "date"), ("Посилання", "url", True)], ("Активна", "На перегляді", "Скасована"), (1,)),
    "food_waste": register("Списання продуктів", "Категорії втрат, вага й вартість списання.", QUALITY,
        [("Продукт", "text"), ("Втрачено, кг", "number"), ("Вартість, грн", "number"), ("Причина", "text"), ("Дата", "date")], ("На перевірці", "Списано"), (1, 2)),
    "print_jobs": register("Замовлення на друк", "Формати, тиражі й готовність виробництва.", QUALITY,
        [("Замовник", "text"), ("Формат", "text"), ("Тираж", "number"), ("Дата видачі", "date")], ("Прийнято", "Макет", "Друк", "Готово", "Видано"), (2,)),
}

TRANSFORMS = {
    "dedupe_lines": transform("Очищення списку від повторів", "Видаліть однакові рядки й побачте кількість повторів.",
        (("Вхідний список", "long", True),), data.unique_lines),
    "text_counts": transform("Статистика тексту", "Порахуйте слова й символи та знайдіть найчастіші слова.",
        (("Текст", "long", True),), data.text_counts),
    "phone_cleanup": transform("Нормалізація номерів", "Приведіть список телефонів до E.164 та знайдіть помилки.",
        (("Номери, по одному на рядок", "long", True),), data.clean_phones),
    "csv_unique": transform("Повтори в таблиці", "Приберіть повністю однакові рядки CSV.",
        (("CSV із заголовком", "csv", True),), data.csv_unique),
    "csv_summary": transform("Підсумки CSV за групами", "Порахуйте суму, кількість і середнє за кожною категорією.",
        (("CSV із заголовком", "csv", True), ("Стовпець групи", "text", True), ("Числовий стовпець", "text", True)), data.csv_summary),
    "csv_merge": transform("Об’єднання двох таблиць", "З’єднайте CSV за унікальним ключем у першому стовпці.",
        (("Таблиця A", "csv", True), ("Таблиця B", "csv", True)), data.csv_merge),
    "csv_compare": transform("Відмінності у двох CSV", "Покажіть додані й вилучені ключі та зміни окремих значень.",
        (("Попередня таблиця", "csv", True), ("Поточна таблиця", "csv", True)), data.csv_compare),
    "checklist_progress": transform("Прогрес чекліста", "Порахуйте виконане в списку з позначками [x] та [ ].",
        (("Пункти чекліста", "long", True),), data.checklist_progress),
    "date_intervals": transform("Інтервали між датами", "Порахувати дні між подіями у форматі РРРР-ММ-ДД.",
        (("Дати, по одній на рядок", "long", True),), data.date_intervals),
    "rank_options": transform("Порівняння за критеріями", "Рейтинг альтернатив за балами й вагою. Стовпці option;score;weight.",
        (("Таблиця оцінок", "csv", True),), data.rank_options),
    "shift_plan": transform("Генератор чергувань", "Розподіліть дні між учасниками по черзі.",
        (("Учасники, по одному на рядок", "long", True), ("Перший день", "date", True), ("Кількість днів", "number", True),
         ("Пропустити суботу й неділю", "toggle", False)), data.shift_plan),
    "service_slots": transform("Розмітка слотів", "Розбийте робочі години на рівні інтервали з перервами.",
        (("Дата", "date", True), ("Від", "time", True), ("До", "time", True), ("Тривалість, хв", "number", True),
         ("Перерва, хв", "number", True)), data.service_slots),
    "receipt_split": transform("Поділ чека", "Розділіть суму порівну між учасниками до копійки.",
        (("Загальна сума", "number", True), ("Імена, по одному на рядок", "long", True)), data.receipt_split),
    "utm_builder": transform("UTM-посилання", "Додайте мітки джерела, каналу й кампанії до адреси.",
        (("Посилання", "url", True), ("Джерело", "text", True), ("Канал", "text", True), ("Кампанія", "text", True),
         ("Варіант оголошення", "text", False)), data.utm_builder),
}

WORKFLOWS = {**CALCULATIONS, **REGISTERS, **TRANSFORMS}
