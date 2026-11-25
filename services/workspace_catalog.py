"""The catalog is also the server-side authorization policy for module routes."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    label: str
    description: str
    path: str = ""


MODULES = {
    "appointments": Module("Календар записів", "Графік команди та візити", "/admin#day-agenda"),
    "guests": Module("Клієнтська база", "Контакти й історія візитів", "/admin/klienci"),
    "revenue": Module("Виручка", "Звіти щодо візитів та експорт CSV", "/admin/reports"),
    "stock": Module("Склад", "Товари, залишки й рух запасів", "/admin/finance"),
    "team": Module("Команда і послуги", "Майстри, перелік послуг і ціни", "/admin/settings"),
    "activity": Module("Історія дій", "Дії співробітників у просторі", "/admin/logs"),
    "directory": Module("Публічний профіль", "Публікація в каталозі та години роботи", "/workspace/listing"),
    "reconcile": Module("Звірка післяплати", "Дві таблиці з ТТН та сумами → список розбіжностей"),
    "extras": Module("Погодження допробіт", "Надішліть замовнику кошторис на підтвердження"),
    "invoices": Module("Ціни постачальників", "Зміни цін з урахуванням фасування"),
    "checkout": Module("Моніторинг покупки", "Результати регулярної перевірки шляху покупця"),
    "feeds": Module("Перевірка товарного фіда", "Перевірка XML для Google Shopping"),
    "tender": Module("Перевірка документів", "Чекліст вимог тендера з посиланням на сторінки"),
    "cutting": Module("Карта розкрою", "Розміщення деталей на плитах з урахуванням пропилу"),
    "preflight": Module("Перевірка PDF для друку", "Формат, вильоти та зображення"),
    "cars": Module("Порівняння автомобілів", "Добірка оголошень, оцінка і питання продавцю"),
    "book": Module("Сімейна книга", "Розділи, голосові записи та версія для друку"),
    "notes": Module("Нотатки", "Окремі записи з можливістю редагування"),
    "tasks": Module("Завдання", "Строки та статус виконання"),
    "budget": Module("Кошторис", "Доходи й витрати з підсумком"),
    "time": Module("Облік часу", "Години, ставки і підсумок за проєктом"),
    "links": Module("Посилання", "Зберігайте потрібні сайти і ресурси"),
    "contacts": Module("Адресна книга", "Вибрані контакти команди та партнерів"),
    "files": Module("Документи", "Приватні файли з завантаженням"),
    "decisions": Module("Журнал рішень", "Рішення та їх обґрунтування"),
    "tables": Module("Власні таблиці", "Створіть модуль з полями й експортом", "/workspace/tables"),
}

COMMON = ("notes", "tasks", "files", "links")
SERVICE = ("appointments", "guests", "revenue", "stock", "team", "activity")


@dataclass(frozen=True)
class Industry:
    label: str
    plan: str
    modules: tuple[str, ...]


INDUSTRIES = {
    "barbershop": Industry("Барбершоп / салон", "plan1", SERVICE + ("directory",)),
    "clinic": Industry("Клініка / стоматологія", "plan1", SERVICE),
    "carwash": Industry("Детейлінг / СТО", "plan1", SERVICE + ("budget",)),
    "spa": Industry("SPA / масаж", "plan1", SERVICE + ("directory",)),
    "retail": Industry("Інтернет-магазин", "commerce", ("reconcile", "checkout", "feeds", "stock", "budget")),
    "restaurant": Industry("Ресторан / кафе", "commerce", ("invoices", "budget", "stock", "team")),
    "construction": Industry("Ремонт і будівництво", "production", ("extras", "budget", "time", "decisions")),
    "tenders": Industry("Постачальник Prozorro", "production", ("tender", "budget", "decisions")),
    "furniture": Industry("Меблева майстерня", "production", ("cutting", "budget", "stock", "extras")),
    "print": Industry("Типографія", "production", ("preflight", "budget", "extras")),
    "cars": Industry("Підбір автомобілів", "plan1", ("cars", "budget", "contacts")),
    "family": Industry("Сімейні проєкти", "plan1", ("book",)),
    "other": Industry("Різне · конструктор", "custom", ("notes", "tasks", "budget")),
}

PLAN_NAMES = {
    "plan1": "Business",
    "plan2": "Business Pro",
    "commerce": "Commerce",
    "production": "Workshop",
    "custom": "Конструктор",
}


def allowed_modules(business):
    if business.plan_type == "custom":
        return tuple(MODULES)
    if business.type not in INDUSTRIES:
        return SERVICE + COMMON
    return tuple(dict.fromkeys(INDUSTRIES[business.type].modules + COMMON))


def industry_plan(industry, requested):
    plan = INDUSTRIES[industry].plan
    return "plan2" if requested == "plan2" and plan == "plan1" else plan
