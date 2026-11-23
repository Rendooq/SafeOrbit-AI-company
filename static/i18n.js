(function () {
    "use strict";

    const STORAGE_KEY = "safeorbit.language";
    const CURRENCY_STORAGE_KEY = "safeorbit.currency";
    const MACHINE_TRANSLATION_ENABLED = false;
    const SUPPORTED = {
        en: { label: "English", htmlLang: "en" },
        ru: { label: "Русский", htmlLang: "ru" },
        uk: { label: "Українська", htmlLang: "uk" },
        pl: { label: "Polski", htmlLang: "pl" },
        zh: { label: "中文", htmlLang: "zh-CN" },
    };
    const CURRENCIES = {
        UAH: { label: "UAH", symbol: "₴", rate: 1, locale: "uk-UA" },
        USD: { label: "USD", symbol: "$", rate: 41.5, locale: "en-US" },
        EUR: { label: "EUR", symbol: "€", rate: 45.0, locale: "de-DE" },
        PLN: { label: "PLN", symbol: "zł", rate: 10.5, locale: "pl-PL" },
        CNY: { label: "CNY", symbol: "¥", rate: 5.75, locale: "zh-CN" },
        GBP: { label: "GBP", symbol: "£", rate: 53.0, locale: "en-GB" },
    };

    const translations = {
        en: Object.create(null),
        ru: Object.create(null),
        pl: Object.create(null),
        zh: Object.create(null),
    };

    function add(source, en, ru, pl, zh) {
        translations.en[source] = en;
        translations.ru[source] = ru;
        translations.pl[source] = pl;
        translations.zh[source] = zh;
    }

    [
        ["Адмінпанель", "Admin panel", "Админпанель", "Panel admina", "管理面板"],
        ["Аналітика", "Analytics", "Аналитика", "Analityka", "分析"],
        ["Конфігурація", "Configuration", "Конфигурация", "Konfiguracja", "配置"],
        ["Склад", "Inventory", "Склад", "Magazyn", "库存"],
        ["Журнал подій", "Event log", "Журнал событий", "Dziennik zdarzeń", "事件日志"],
        ["Комунікації", "Communications", "Коммуникации", "Komunikacja", "通信"],
        ["AI Сервіс", "AI service", "AI сервис", "Usługa AI", "AI 服务"],
        ["AI Асистенти", "AI assistants", "AI ассистенты", "Asystenci AI", "AI 助手"],
        ["Інтелектуальний Асистент", "Intelligent assistant", "Интеллектуальный ассистент", "Inteligentny asystent", "智能助手"],
        ["Оновлення", "Updates", "Обновления", "Aktualizacje", "更新"],
        ["Підтримка", "Support", "Поддержка", "Wsparcie", "支持"],
        ["Панель", "Dashboard", "Панель", "Panel", "面板"],
        ["Пошук...", "Search...", "Поиск...", "Szukaj...", "搜索..."],
        ["Нічого не знайдено", "Nothing found", "Ничего не найдено", "Nic nie znaleziono", "未找到结果"],
        ["Гість", "Guest", "Гость", "Gość", "访客"],
        ["Клієнт", "Client", "Клиент", "Klient", "客户"],
        ["Запис", "Appointment", "Запись", "Wizyta", "预约"],
        ["Сервіс", "Service", "Сервис", "Usługa", "服务"],
        ["Завершити сесію", "Log out", "Завершить сессию", "Zakończ sesję", "退出登录"],
        ["Сховати панель", "Hide sidebar", "Скрыть панель", "Ukryj panel", "隐藏侧边栏"],
        ["Завантаження...", "Loading...", "Загрузка...", "Ładowanie...", "加载中..."],
        ["Адміністратор", "Administrator", "Администратор", "Administrator", "管理员"],
        ["Експерт", "Expert", "Эксперт", "Ekspert", "专家"],
        ["Власник", "Owner", "Владелец", "Właściciel", "所有者"],
        ["Зміни збережено!", "Changes saved!", "Изменения сохранены!", "Zmiany zapisane!", "更改已保存！"],
        ["Збережено!", "Saved!", "Сохранено!", "Zapisano!", "已保存！"],
        ["Запис успішно додано!", "Appointment added successfully!", "Запись успешно добавлена!", "Wizyta została dodana!", "预约已成功添加！"],
        ["Запис видалено!", "Record deleted!", "Запись удалена!", "Wpis usunięty!", "记录已删除！"],
        ["Цей час вже зайнятий!", "This time is already booked!", "Это время уже занято!", "Ten termin jest już zajęty!", "该时间已被预约！"],
        ["Повідомлення відправлено!", "Message sent!", "Сообщение отправлено!", "Wiadomość wysłana!", "消息已发送！"],
        ["Запис додано та синхронізовано!", "Appointment added and synced!", "Запись добавлена и синхронизирована!", "Wizyta dodana i zsynchronizowana!", "预约已添加并同步！"],
        ["Філію створено!", "Branch created!", "Филиал создан!", "Oddział utworzony!", "分店已创建！"],
        ["Філію видалено!", "Branch deleted!", "Филиал удален!", "Oddział usunięty!", "分店已删除！"],
        ["Такий логін вже існує!", "This login already exists!", "Такой логин уже существует!", "Taki login już istnieje!", "该登录名已存在！"],
        ["Розсилку відправлено!", "Broadcast sent!", "Рассылка отправлена!", "Wysyłka została wysłana!", "群发已发送！"],
        ["Приховати ключ", "Hide key", "Скрыть ключ", "Ukryj klucz", "隐藏密钥"],
        ["Показати ключ", "Show key", "Показать ключ", "Pokaż klucz", "显示密钥"],
        ["API ключ скопійовано!", "API key copied!", "API ключ скопирован!", "Klucz API skopiowany!", "API 密钥已复制！"],
        ["Dashboard", "Dashboard", "Панель", "Dashboard", "仪表盘"],
        ["Список", "List", "Список", "Lista", "列表"],
        ["Календар", "Calendar", "Календарь", "Kalendarz", "日历"],
        ["Статистика", "Statistics", "Статистика", "Statystyki", "统计"],
        ["Очікується", "Expected", "Ожидается", "Oczekiwane", "待处理"],
        ["Виконано", "Done", "Выполнено", "Wykonane", "已完成"],
        ["Скасовано", "Cancelled", "Отменено", "Anulowane", "已取消"],
        ["Сьогодні", "Today", "Сегодня", "Dzisiaj", "今天"],
        ["Поточний місяць", "Current month", "Текущий месяц", "Bieżący miesiąc", "本月"],
        ["Оборот", "Circulation", "Оборот", "Obrót", "流水"],
        ["За весь період", "For the entire period", "За весь период", "Za cały okres", "整个期间"],
        ["Контактний номер", "Contact number", "Контактный номер", "Numer kontaktowy", "联系电话"],
        ["Профіль гостя", "Guest profile", "Профиль гостя", "Profil gościa", "访客资料"],
        ["Обраний сервіс", "Selected service", "Выбранный сервис", "Wybrana usługa", "已选服务"],
        ["СУМА ДО СПЛАТИ", "Amount payable", "Сумма к оплате", "Kwota do zapłaty", "应付金额"],
        ["Будь-який", "Any", "Любой", "Dowolny", "任意"],
        ["Будь-який --", "Any", "Любой", "Dowolny", "任意"],
        ["-- Будь-який --", "-- Any --", "-- Любой --", "-- Dowolny --", "-- 任意 --"],
        ["Оберіть сервіс", "Choose a service", "Выберите сервис", "Wybierz usługę", "选择服务"],
        ["-- Оберіть сервіс --", "-- Choose a service --", "-- Выберите сервис --", "-- Wybierz usługę --", "-- 选择服务 --"],
        ["Підтвердити запис", "Confirm booking", "Подтвердить запись", "Potwierdź rezerwację", "确认预约"],
        ["NE", "NE", "NE", "NE", "NE"],
        ["Віджет", "Widget", "Виджет", "Widget", "小组件"],
        ["Єдина база контактів, знижок, статусів і нотаток", "A clean contact base with discounts, statuses, and notes", "Единая база контактов, скидок, статусов и заметок", "Jedna baza kontaktów, rabatów, statusów i notatek", "统一管理联系人、折扣、状态和备注"],
        ["База клієнтів", "Guest profiles", "Профили гостей", "Profile gości", "访客资料"],
        ["База профілів гостей", "Guest profiles", "Профили гостей", "Profile gości", "访客资料"],

        ["Профілі гостей", "Guest profiles", "Профили гостей", "Profile gości", "访客资料"],
        ["Профілі пацієнтів", "Patient profiles", "Профили пациентов", "Profile pacjentów", "患者资料"],
        ["Профілі покупців", "Customer profiles", "Профили покупателей", "Profile klientów", "客户资料"],
        ["Експерти", "Experts", "Эксперты", "Eksperci", "专家"],
        ["Лікарі", "Doctors", "Врачи", "Lekarze", "医生"],
        ["Сервіси", "Services", "Сервисы", "Usługi", "服务"],
        ["Процедури", "Procedures", "Процедуры", "Procedury", "项目"],
        ["Тренування", "Training sessions", "Тренировки", "Treningi", "训练课程"],
        ["Товари", "Products", "Товары", "Produkty", "商品"],
        ["Реєстрація візиту", "Visit registration", "Регистрация визита", "Rejestracja wizyty", "登记访问"],
        ["Реєстрація замовлення", "Order registration", "Регистрация заказа", "Rejestracja zamówienia", "登记订单"],
        ["Історія активності", "Activity history", "История активности", "Historia aktywności", "活动历史"],
        ["Експерт", "Expert", "Эксперт", "Ekspert", "专家"],
        ["Лікар", "Doctor", "Врач", "Lekarz", "医生"],
        ["Менеджер", "Manager", "Менеджер", "Menedżer", "经理"],
        ["Товар", "Product", "Товар", "Produkt", "产品"],
        ["ВІЗИТІВ СЬОГОДНІ", "VISITS TODAY", "ВИЗИТОВ СЕГОДНЯ", "WIZYTY DZISIAJ", "今日访问"],
        ["ВІЗИТІВ МІСЯЦЬ", "VISITS THIS MONTH", "ВИЗИТОВ ЗА МЕСЯЦ", "WIZYTY W MIESIĄCU", "本月访问"],
        ["ДОХІД МІСЯЦЬ", "MONTHLY REVENUE", "ДОХОД ЗА МЕСЯЦ", "PRZYCHÓD MIESIĄCA", "本月收入"],
        ["ДОХІД ВСЬОГО", "TOTAL REVENUE", "ДОХОД ВСЕГО", "PRZYCHÓD ŁĄCZNIE", "总收入"],
        ["ЗАМОВЛЕНЬ СЬОГОДНІ", "ORDERS TODAY", "ЗАКАЗОВ СЕГОДНЯ", "ZAMÓWIENIA DZISIAJ", "今日订单"],
        ["ЗАМОВЛЕНЬ МІСЯЦЬ", "ORDERS THIS MONTH", "ЗАКАЗОВ ЗА МЕСЯЦ", "ZAMÓWIENIA W MIESIĄCU", "本月订单"],
        ["ВИРУЧКА МІСЯЦЬ", "MONTHLY SALES", "ВЫРУЧКА ЗА МЕСЯЦ", "SPRZEDAŻ MIESIĄCA", "本月销售额"],
        ["ВИРУЧКА ВСЬОГО", "TOTAL SALES", "ОБЩАЯ ВЫРУЧКА", "SPRZEDAŻ ŁĄCZNIE", "总销售额"],
        ["Джерела записів", "Booking sources", "Источники записей", "Źródła rezerwacji", "预约来源"],
        ["Популярність сервісів", "Service popularity", "Популярность сервисов", "Popularność usług", "服务热度"],
        ["Популярність процедур", "Procedure popularity", "Популярность процедур", "Popularność procedur", "项目热度"],
        ["Популярність тренувань", "Training popularity", "Популярность тренировок", "Popularność treningów", "训练热度"],
        ["Популярність товарів", "Product popularity", "Популярность товаров", "Popularność produktów", "商品热度"],
        ["Топ-5 Гостей (LTV)", "Top 5 guests (LTV)", "Топ-5 гостей (LTV)", "Top 5 gości (LTV)", "访客前 5 名 (LTV)"],
        ["Топ-5 Пацієнтів (LTV)", "Top 5 patients (LTV)", "Топ-5 пациентов (LTV)", "Top 5 pacjentów (LTV)", "患者前 5 名 (LTV)"],
        ["Топ-5 Покупців (LTV)", "Top 5 customers (LTV)", "Топ-5 покупателей (LTV)", "Top 5 klientów (LTV)", "客户前 5 名 (LTV)"],

        ["Реєстрація", "Registration", "Регистрация", "Rejestracja", "注册"],
        ["Реєстрація | SafeOrbit", "Registration | SafeOrbit", "Регистрация | SafeOrbit", "Rejestracja | SafeOrbit", "注册 | SafeOrbit"],
        ["Вхід | SafeOrbit", "Login | SafeOrbit", "Вход | SafeOrbit", "Logowanie | SafeOrbit", "登录 | SafeOrbit"],
        ["Premium CRM Experience", "Premium CRM Experience", "Премиальный CRM опыт", "Premium CRM Experience", "高级 CRM 体验"],
        ["Почніть свій шлях з SafeOrbit", "Start your journey with SafeOrbit", "Начните свой путь с SafeOrbit", "Rozpocznij pracę z SafeOrbit", "从 SafeOrbit 开始您的旅程"],
        ["Телефон", "Phone", "Телефон", "Telefon", "电话"],
        ["Телефон (ваш логін)", "Phone (your login)", "Телефон (ваш логин)", "Telefon (login)", "电话（您的登录名）"],
        ["Пароль", "Password", "Пароль", "Hasło", "密码"],
        ["Увійти", "Log in", "Войти", "Zaloguj", "登录"],
        ["Тестовий акаунт", "Demo account", "Тестовый аккаунт", "Konto testowe", "演示账户"],
        ["Немає акаунту?", "No account?", "Нет аккаунта?", "Nie masz konta?", "没有账户？"],
        ["Створити бізнес", "Create a business", "Создать бизнес", "Utwórz firmę", "创建企业"],
        ["Вже є акаунт?", "Already have an account?", "Уже есть аккаунт?", "Masz już konto?", "已有账户？"],
        ["Створити акаунт", "Create account", "Создать аккаунт", "Utwórz konto", "创建账户"],
        ["Створити бізнес-акаунт", "Create business account", "Создать бизнес-аккаунт", "Utwórz konto firmowe", "创建企业账户"],
        ["Назва бізнесу", "Business name", "Название бизнеса", "Nazwa firmy", "企业名称"],
        ["Введіть назву...", "Enter a name...", "Введите название...", "Wpisz nazwę...", "输入名称..."],
        ["Сфера діяльності", "Business area", "Сфера деятельности", "Branża", "业务领域"],
        ["Категорія товарів", "Product category", "Категория товаров", "Kategoria produktów", "商品类别"],
        ["Салон краси / Барбершоп", "Beauty salon / Barbershop", "Салон красоты / Барбершоп", "Salon beauty / Barbershop", "美容院 / 理发店"],
        ["Стоматологія", "Dentistry", "Стоматология", "Stomatologia", "牙科"],
        ["Медичний центр", "Medical center", "Медицинский центр", "Centrum medyczne", "医疗中心"],
        ["Фітнес / Спорт", "Fitness / Sports", "Фитнес / Спорт", "Fitness / Sport", "健身 / 运动"],
        ["Магазин / Товарний бізнес", "Store / Product business", "Магазин / Товарный бизнес", "Sklep / Handel", "商店 / 商品业务"],
        ["Школа / Навчальний центр", "School / Training center", "Школа / Учебный центр", "Szkoła / Centrum szkoleniowe", "学校 / 培训中心"],
        ["Інше", "Other", "Другое", "Inne", "其他"],
        ["Одяг та взуття", "Clothing and shoes", "Одежда и обувь", "Odzież i obuwie", "服装和鞋类"],
        ["Електроніка", "Electronics", "Электроника", "Elektronika", "电子产品"],
        ["Косметика", "Cosmetics", "Косметика", "Kosmetyki", "化妆品"],
        ["Дім та сад", "Home and garden", "Дом и сад", "Dom i ogród", "家居与花园"],
        ["Дитячі товари", "Kids products", "Детские товары", "Artykuły dziecięce", "儿童用品"],
        ["Спорт", "Sports", "Спорт", "Sport", "运动"],
        ["Автотовари", "Auto products", "Автотовары", "Artykuły samochodowe", "汽车用品"],
        ["Оберіть тарифний план", "Choose a pricing plan", "Выберите тарифный план", "Wybierz plan taryfowy", "选择套餐"],
        ["Тимчасово недоступний", "Temporarily unavailable", "Временно недоступен", "Tymczasowo niedostępne", "暂时不可用"],
        ["Маєте промокод?", "Have a promo code?", "Есть промокод?", "Masz kod promocyjny?", "有优惠码？"],
        ["Введіть код...", "Enter code...", "Введите код...", "Wpisz kod...", "输入代码..."],
        ["Застосувати", "Apply", "Применить", "Zastosuj", "应用"],
        ["Документи", "Documents", "Документы", "Dokumenty", "文件"],
        ["Підписаний NDA", "Signed NDA", "Подписанный NDA", "Podpisane NDA", "已签署 NDA"],
        ["Підписаний Договір", "Signed contract", "Подписанный договор", "Podpisana umowa", "已签署合同"],
        ["Оплата підписки", "Subscription payment", "Оплата подписки", "Płatność za subskrypcję", "订阅付款"],
        ["До сплати:", "Amount due:", "К оплате:", "Do zapłaty:", "应付金额："],
        ["IBAN реквізити", "IBAN details", "Реквизиты IBAN", "Dane IBAN", "IBAN 信息"],
        ["QR-код", "QR code", "QR-код", "Kod QR", "二维码"],
        ["Натисніть для копіювання", "Click to copy", "Нажмите для копирования", "Kliknij, aby skopiować", "点击复制"],
        ["Отримувач:", "Recipient:", "Получатель:", "Odbiorca:", "收款人："],
        ["Чек про оплату", "Payment receipt", "Чек об оплате", "Potwierdzenie płatności", "付款凭证"],
        ["Я погоджуюся з умовами використання та обробкою персональних даних", "I agree to the terms of use and personal data processing", "Я соглашаюсь с условиями использования и обработкой персональных данных", "Akceptuję regulamin i przetwarzanie danych osobowych", "我同意使用条款和个人数据处理"],
        ["Скопійовано!", "Copied!", "Скопировано!", "Skopiowano!", "已复制！"],
        ["Недійсний промокод", "Invalid promo code", "Недействительный промокод", "Nieprawidłowy kod promocyjny", "无效优惠码"],
        ["Термін дії промокоду минув", "Promo code has expired", "Срок действия промокода истек", "Kod promocyjny wygasł", "优惠码已过期"],
        ["Промокод застосовано!", "Promo code applied!", "Промокод применен!", "Kod promocyjny zastosowany!", "优惠码已应用！"],
        ["Успішно!", "Success!", "Успешно!", "Sukces!", "成功！"],
        ["Заявка відправлена. Адміністратор активує ваш акаунт після перевірки.", "Request sent. The administrator will activate your account after review.", "Заявка отправлена. Администратор активирует ваш аккаунт после проверки.", "Zgłoszenie wysłane. Administrator aktywuje konto po weryfikacji.", "申请已发送。管理员审核后将激活您的账户。"],
        ["Заявку Відхилено", "Request rejected", "Заявка отклонена", "Zgłoszenie odrzucone", "申请被拒绝"],
        ["Причина відмови:", "Rejection reason:", "Причина отказа:", "Powód odmowy:", "拒绝原因："],
        ["Не вказана", "Not specified", "Не указана", "Nie podano", "未指定"],
        ["На жаль, вашу заявку на реєстрацію було відхилено. Ви можете звернутися до підтримки для вирішення проблеми.", "Unfortunately, your registration request was rejected. You can contact support to resolve the issue.", "К сожалению, ваша заявка на регистрацию была отклонена. Вы можете обратиться в поддержку для решения проблемы.", "Niestety zgłoszenie rejestracyjne zostało odrzucone. Możesz skontaktować się ze wsparciem.", "很遗憾，您的注册申请被拒绝。您可以联系支持解决问题。"],
        ["Очікує Активації", "Awaiting activation", "Ожидает активации", "Oczekuje na aktywację", "等待激活"],
        ["Ваша заявка успішно надіслана та наразі перевіряється адміністратором. Будь ласка, зачекайте на підтвердження.", "Your request was sent and is being reviewed by an administrator. Please wait for confirmation.", "Ваша заявка успешно отправлена и сейчас проверяется администратором. Пожалуйста, дождитесь подтверждения.", "Zgłoszenie zostało wysłane i jest sprawdzane przez administratora. Poczekaj na potwierdzenie.", "您的申请已发送，管理员正在审核。请等待确认。"],
        ["Акаунт Заблоковано", "Account blocked", "Аккаунт заблокирован", "Konto zablokowane", "账户已被封禁"],
        ["Доступ до вашого акаунту тимчасово призупинено.", "Access to your account has been temporarily suspended.", "Доступ к вашему аккаунту временно приостановлен.", "Dostęp do konta został tymczasowo zawieszony.", "您的账户访问已被暂时暂停。"],
        ["Зверніться до адміністратора.", "Contact the administrator.", "Обратитесь к администратору.", "Skontaktuj się z administratorem.", "请联系管理员。"],
        ["Повернутися", "Go back", "Вернуться", "Wróć", "返回"],
        ["На головну", "Home", "На главную", "Na stronę główną", "首页"],
        ["Акаунт Активовано", "Account activated", "Аккаунт активирован", "Konto aktywowane", "账户已激活"],
        ["Вашу заявку успішно схвалено! Тепер ви можете увійти в свій особистий кабінет.", "Your request has been approved. You can now log in to your account.", "Ваша заявка успешно одобрена! Теперь вы можете войти в личный кабинет.", "Twoje zgłoszenie zostało zaakceptowane. Możesz teraz zalogować się do konta.", "您的申请已通过！现在可以登录您的账户。"],
        ["Заявку прийнято", "Request received", "Заявка принята", "Zgłoszenie przyjęte", "申请已接收"],
        ["Ваш акаунт наразі перевіряється адміністратором. Ви зможете увійти в систему після підтвердження.", "Your account is being reviewed by an administrator. You will be able to log in after confirmation.", "Ваш аккаунт сейчас проверяется администратором. Вы сможете войти после подтверждения.", "Twoje konto jest sprawdzane przez administratora. Zalogujesz się po potwierdzeniu.", "您的账户正在由管理员审核。确认后即可登录。"],
        ["Цей номер вже зареєстровано. Поверніться назад.", "This number is already registered. Please go back.", "Этот номер уже зарегистрирован. Вернитесь назад.", "Ten numer jest już zarejestrowany. Wróć.", "该号码已注册。请返回。"],

        ["Онлайн-запис", "Online booking", "Онлайн-запись", "Rezerwacja online", "在线预约"],
        ["Оберіть послугу та зручний час", "Choose a service and convenient time", "Выберите услугу и удобное время", "Wybierz usługę i dogodny termin", "选择服务和方便时间"],
        ["Деталі візиту", "Visit details", "Детали визита", "Szczegóły wizyty", "访问详情"],
        ["Що замовляємо?", "What are we ordering?", "Что заказываем?", "Co zamawiamy?", "要订购什么？"],
        ["Оберіть дату", "Choose a date", "Выберите дату", "Wybierz datę", "选择日期"],
        ["Бажана дата отримання", "Preferred pickup date", "Желаемая дата получения", "Preferowana data odbioru", "期望取货日期"],
        ["Оберіть час", "Choose a time", "Выберите время", "Wybierz godzinę", "选择时间"],
        ["Орієнтовний час", "Approximate time", "Ориентировочное время", "Orientacyjna godzina", "大致时间"],
        ["Підтвердити запис", "Confirm booking", "Подтвердить запись", "Potwierdź rezerwację", "确认预约"],
        ["Підтвердити замовлення", "Confirm order", "Подтвердить заказ", "Potwierdź zamówienie", "确认订单"],
        ["Доставка", "Delivery", "Доставка", "Dostawa", "配送"],
        ["Місто, № відділення пошти або адреса...", "City, post office branch number, or address...", "Город, № отделения почты или адрес...", "Miasto, nr placówki pocztowej lub adres...", "城市、邮局网点编号或地址..."],
        ["Оберіть сервіс...", "Choose a service...", "Выберите сервис...", "Wybierz usługę...", "选择服务..."],
        ["Оберіть послугу...", "Choose a service...", "Выберите услугу...", "Wybierz usługę...", "选择服务..."],
        ["Оберіть товар...", "Choose a product...", "Выберите товар...", "Wybierz produkt...", "选择商品..."],
        ["Будь-який експерт", "Any expert", "Любой эксперт", "Dowolny ekspert", "任意专家"],
        ["Будь-який лікар", "Any doctor", "Любой врач", "Dowolny lekarz", "任意医生"],
        ["Будь-який менеджер", "Any manager", "Любой менеджер", "Dowolny menedżer", "任意经理"],
        ["Ваші контакти", "Your contacts", "Ваши контакты", "Twoje dane kontaktowe", "您的联系方式"],
        ["Ім'я", "Name", "Имя", "Imię", "姓名"],
        ["Спочатку оберіть дату", "Choose a date first", "Сначала выберите дату", "Najpierw wybierz datę", "请先选择日期"],
        ["Будь ласка, оберіть дату та час візиту!", "Please choose the visit date and time!", "Пожалуйста, выберите дату и время визита!", "Wybierz datę i godzinę wizyty!", "请选择访问日期和时间！"],
        ["Ваш запис успішно створено! Чекаємо на вас.", "Your booking was created successfully. We are waiting for you.", "Ваша запись успешно создана! Ждем вас.", "Twoja rezerwacja została utworzona. Czekamy na Ciebie.", "您的预约已成功创建！期待您的到来。"],
        ["На жаль, цей час вже зайнятий. Оберіть інший.", "Unfortunately, this time is already booked. Choose another one.", "К сожалению, это время уже занято. Выберите другое.", "Niestety ten termin jest już zajęty. Wybierz inny.", "很遗憾，该时间已被预约。请选择其他时间。"],
        ["Цей час вже минув. Оберіть інший.", "This time has already passed. Choose another one.", "Это время уже прошло. Выберите другое.", "Ten termin już minął. Wybierz inny.", "该时间已过去。请选择其他时间。"],
        ["Вибачте, бронювання для вашого номера тимчасово недоступне.", "Sorry, booking for your number is temporarily unavailable.", "Извините, бронирование для вашего номера временно недоступно.", "Przepraszamy, rezerwacja dla Twojego numeru jest tymczasowo niedostępna.", "抱歉，您的号码暂时无法预约。"],
        ["Бізнес не знайдено або заблоковано", "Business not found or blocked", "Бизнес не найден или заблокирован", "Firmy nie znaleziono lub jest zablokowana", "未找到企业或企业已被封禁"],
        ["Бізнес не знайдено", "Business not found", "Бизнес не найден", "Nie znaleziono firmy", "未找到企业"],
        ["З радістю допоможу вам зареєструвати візит! Оберіть сервіс та зручний час.", "I will gladly help you book a visit. Choose a service and convenient time.", "С радостью помогу вам записаться! Выберите сервис и удобное время.", "Chętnie pomogę zarezerwować wizytę. Wybierz usługę i dogodny termin.", "我很乐意帮您预约！请选择服务和方便时间。"],
        ["Вибачте, виникла помилка. Спробуйте пізніше.", "Sorry, an error occurred. Try again later.", "Извините, произошла ошибка. Попробуйте позже.", "Przepraszamy, wystąpił błąd. Spróbuj później.", "抱歉，发生错误。请稍后再试。"],
        ["Будь ласка, вкажіть телефон та дату.", "Please provide phone and date.", "Пожалуйста, укажите телефон и дату.", "Podaj telefon i datę.", "请提供电话和日期。"],
        ["Послугу не знайдено", "Service not found", "Услуга не найдена", "Nie znaleziono usługi", "未找到服务"],
        ["Цей час вже минув.", "This time has already passed.", "Это время уже прошло.", "Ten termin już minął.", "该时间已过去。"],
        ["Помилка при створенні запису.", "Error while creating booking.", "Ошибка при создании записи.", "Błąd podczas tworzenia rezerwacji.", "创建预约时出错。"],

        ["Діалоги", "Conversations", "Диалоги", "Dialogi", "对话"],
        ["Оберіть діалог для початку спілкування", "Choose a conversation to start chatting", "Выберите диалог, чтобы начать общение", "Wybierz dialog, aby rozpocząć rozmowę", "选择对话开始聊天"],
        ["Немає діалогів", "No conversations", "Нет диалогов", "Brak dialogów", "没有对话"],
        ["Немає повідомлень", "No messages", "Нет сообщений", "Brak wiadomości", "没有消息"],
        ["Написати повідомлення...", "Write a message...", "Написать сообщение...", "Napisz wiadomość...", "输入消息..."],
        ["Відправка...", "Sending...", "Отправка...", "Wysyłanie...", "发送中..."],
        ["Помилка відправки повідомлення", "Message sending error", "Ошибка отправки сообщения", "Błąd wysyłania wiadomości", "消息发送错误"],
        ["Помилка: Відсутній параметр ?api_key у URL", "Error: missing ?api_key parameter in URL", "Ошибка: отсутствует параметр ?api_key в URL", "Błąd: brak parametru ?api_key w URL", "错误：URL 中缺少 ?api_key 参数"],

        ["Назва", "Name", "Название", "Nazwa", "名称"],
        ["ПІБ", "Full name", "ФИО", "Imię i nazwisko", "全名"],
        ["К-сть", "Qty", "Кол-во", "Ilość", "数量"],
        ["Колір", "Color", "Цвет", "Kolor", "颜色"],
        ["Розмір/Об'єм", "Size/Volume", "Размер/Объем", "Rozmiar/Objętość", "尺寸/容量"],
        ["Фото товару", "Product photo", "Фото товара", "Zdjęcie produktu", "商品照片"],
        ["Додати товар на склад", "Add product to inventory", "Добавить товар на склад", "Dodaj produkt do magazynu", "添加商品到库存"],
        ["Додати", "Add", "Добавить", "Dodaj", "添加"],
        ["Зберегти", "Save", "Сохранить", "Zapisz", "保存"],
        ["Видалити", "Delete", "Удалить", "Usuń", "删除"],
        ["Редагувати", "Edit", "Редактировать", "Edytuj", "编辑"],
        ["Блокувати", "Block", "Блокировать", "Zablokuj", "封禁"],
        ["Розблокувати", "Unblock", "Разблокировать", "Odblokuj", "解除封禁"],
        ["Скасувати", "Cancel", "Отменить", "Anuluj", "取消"],
        ["Схвалити", "Approve", "Одобрить", "Zatwierdź", "批准"],
        ["Відхилити", "Reject", "Отклонить", "Odrzuć", "拒绝"],
        ["Видалити?", "Delete?", "Удалить?", "Usunąć?", "删除？"],
        ["Ви впевнені?", "Are you sure?", "Вы уверены?", "Czy na pewno?", "确定吗？"],
        ["Видалити запис?", "Delete appointment?", "Удалить запись?", "Usunąć wizytę?", "删除预约？"],
        ["Видалити товар?", "Delete product?", "Удалить товар?", "Usunąć produkt?", "删除商品？"],
        ["Видалити інтеграцію?", "Delete integration?", "Удалить интеграцию?", "Usunąć integrację?", "删除集成？"],
        ["Видалити бізнес?", "Delete business?", "Удалить бизнес?", "Usunąć firmę?", "删除企业？"],
        ["Видалити платіж?", "Delete payment?", "Удалить платеж?", "Usunąć płatność?", "删除付款？"],
        ["Відхилити заявку?", "Reject request?", "Отклонить заявку?", "Odrzucić zgłoszenie?", "拒绝申请？"],
        ["Видалити філію та всі її дані?", "Delete the branch and all its data?", "Удалить филиал и все его данные?", "Usunąć oddział i wszystkie jego dane?", "删除分店及其所有数据？"],
        ["Ви впевнені, що хочете ВИДАЛИТИ цей API ключ назавжди?", "Are you sure you want to permanently DELETE this API key?", "Вы уверены, что хотите навсегда УДАЛИТЬ этот API ключ?", "Czy na pewno chcesz trwale USUNĄĆ ten klucz API?", "确定要永久删除此 API 密钥吗？"],
        ["Скинути пароль", "Reset password", "Сбросить пароль", "Resetuj hasło", "重置密码"],
        ["Введіть новий пароль", "Enter new password", "Введите новый пароль", "Wpisz nowe hasło", "输入新密码"],
        ["Залиште пустим, щоб не змінювати", "Leave empty to keep unchanged", "Оставьте пустым, чтобы не менять", "Zostaw puste, aby nie zmieniać", "留空则不更改"],
        ["Введіть ID...", "Enter ID...", "Введите ID...", "Wpisz ID...", "输入 ID..."],
        ["Введіть токен...", "Enter token...", "Введите токен...", "Wpisz token...", "输入令牌..."],
        ["Назва сервісу", "Service name", "Название сервиса", "Nazwa usługi", "服务名称"],
        ["Назва філії / групи", "Branch / group name", "Название филиала / группы", "Nazwa oddziału / grupy", "分店 / 群组名称"],
        ["Логін (телефон філії)", "Login (branch phone)", "Логин (телефон филиала)", "Login (telefon oddziału)", "登录名（分店电话）"],
        ["Назва філії (напр. 'На Подолі')", "Branch name (e.g. 'On Podil')", "Название филиала (напр. 'На Подоле')", "Nazwa oddziału (np. 'Na Podolu')", "分店名称（例如“Podil 店”）"],
        ["Адреса (напр. вул. Хрещатик, 1)", "Address (e.g. Khreshchatyk St, 1)", "Адрес (напр. ул. Крещатик, 1)", "Adres (np. ul. Chreszczatyk 1)", "地址（例如 Khreshchatyk 街 1 号）"],
        ["Місто (напр. Київ)", "City (e.g. Kyiv)", "Город (напр. Киев)", "Miasto (np. Kijów)", "城市（例如基辅）"],
        ["Графік (напр. Пн-Пт: 10:00-18:00)", "Schedule (e.g. Mon-Fri: 10:00-18:00)", "График (напр. Пн-Пт: 10:00-18:00)", "Grafik (np. pon.-pt.: 10:00-18:00)", "营业时间（例如周一至周五 10:00-18:00）"],
        ["Пошук сервісів...", "Search services...", "Поиск сервисов...", "Szukaj usług...", "搜索服务..."],
        ["Пошук по базі знань...", "Search the knowledge base...", "Поиск по базе знаний...", "Szukaj w bazie wiedzy...", "搜索知识库..."],
        ["Пошук по базі...", "Search the database...", "Поиск по базе...", "Szukaj w bazie...", "搜索数据库..."],
        ["Введіть повідомлення як адміністратор...", "Enter a message as administrator...", "Введите сообщение как администратор...", "Wpisz wiadomość jako administrator...", "以管理员身份输入消息..."],
        ["Мої підключення", "My connections", "Мои подключения", "Moje połączenia", "我的连接"],
        ["Каталог сервісів", "Service catalog", "Каталог сервисов", "Katalog usług", "服务目录"],
        ["Усі сервіси", "All services", "Все сервисы", "Wszystkie usługi", "所有服务"],
        ["Месенджери", "Messengers", "Мессенджеры", "Komunikatory", "消息工具"],
        ["Платежі", "Payments", "Платежи", "Płatności", "支付"],
        ["Локація (Філія)", "Location (branch)", "Локация (филиал)", "Lokalizacja (oddział)", "位置（分店）"],
        ["Назва (для себе)", "Name (for yourself)", "Название (для себя)", "Nazwa (dla siebie)", "名称（自用）"],
        ["Активувати цю інтеграцію", "Activate this integration", "Активировать эту интеграцию", "Aktywuj tę integrację", "启用此集成"],
        ["Активувати", "Activate", "Активировать", "Aktywuj", "启用"],
        ["API Token / Secret Key", "API token / secret key", "API токен / секретный ключ", "Token API / klucz tajny", "API 令牌 / 密钥"],
        ["Додатковий ID (Company / Location ID)", "Additional ID (Company / Location ID)", "Дополнительный ID (Company / Location ID)", "Dodatkowe ID (Company / Location ID)", "附加 ID（公司 / 位置 ID）"],

        ["На Ви", "Formal address", "На Вы", "Formalnie", "正式称呼"],
        ["На Ти", "Informal address", "На ты", "Nieformalnie", "非正式称呼"],
        ["Дружній", "Friendly", "Дружелюбный", "Przyjazny", "友好"],
        ["Діловий", "Businesslike", "Деловой", "Biznesowy", "商务"],
        ["Елітний", "Premium", "Элитный", "Premium", "高级"],
        ["Нейтрально", "Neutral", "Нейтрально", "Neutralnie", "中性"],
        ["Офіційно", "Official", "Официально", "Oficjalnie", "正式"],
        ["Неформально", "Informal", "Неформально", "Nieformalnie", "非正式"],
        ["Грайливий", "Playful", "Игривый", "Swobodny", "活泼"],
        ["Польська", "Polish", "Польский", "Polski", "波兰语"],
        ["Англійська", "English", "Английский", "Angielski", "英语"],
        ["Українська", "Ukrainian", "Украинский", "Ukraiński", "乌克兰语"],
        ["Коротко", "Short", "Коротко", "Krótko", "简短"],
        ["Середньо", "Medium", "Средне", "Średnio", "中等"],
        ["Розгорнуто", "Detailed", "Развернуто", "Szczegółowo", "详细"],
        ["Лаконічно (коротко)", "Concise (short)", "Лаконично (коротко)", "Lakonicznie (krótko)", "简洁（短）"],
        ["Детально (розгорнуто)", "Detailed (expanded)", "Подробно (развернуто)", "Szczegółowo (rozbudowane)", "详细（扩展）"],
        ["Помірно (1-2)", "Moderate (1-2)", "Умеренно (1-2)", "Umiarkowanie (1-2)", "适中（1-2）"],
        ["Багато (емоційно)", "A lot (emotional)", "Много (эмоционально)", "Dużo (emocjonalnie)", "较多（情感化）"],
        ["Перевести на адміна", "Transfer to admin", "Перевести на админа", "Przekaż administratorowi", "转给管理员"],
        ["Кликати адміна", "Call admin", "Позвать админа", "Wezwij administratora", "呼叫管理员"],
        ["Не відповідати", "Do not reply", "Не отвечать", "Nie odpowiadaj", "不回复"],
        ["Просити уточнити", "Ask to clarify", "Попросить уточнить", "Poproś o doprecyzowanie", "请求澄清"],
        ["Відповісти", "Reply", "Ответить", "Odpowiedz", "回复"],
        ["Заспокоїти", "Reassure", "Успокоить", "Uspokój", "安抚"],
        ["Вибачитись", "Apologize", "Извиниться", "Przeproś", "道歉"],
        ["Ігнорувати", "Ignore", "Игнорировать", "Ignoruj", "忽略"],
        ["Імпровізувати", "Improvise", "Импровизировать", "Improwizuj", "即兴回复"],

        ["Отримано", "Received", "Получено", "Odebrano", "已收到"],
        ["Відмова / Повернення", "Refusal / Return", "Отказ / Возврат", "Odmowa / Zwrot", "拒收 / 退货"],
        ["ТТН (Номер накладної)", "Tracking number", "ТТН (номер накладной)", "Numer przesyłki", "运单号"],
        ["Місто, відділення...", "City, branch...", "Город, отделение...", "Miasto, oddział...", "城市、网点..."],
        ["Введіть адресу доставки...", "Enter delivery address...", "Введите адрес доставки...", "Wpisz adres dostawy...", "输入配送地址..."],

        ["Всі", "All", "Все", "Wszystkie", "全部"],
        ["Початок роботи", "Getting started", "Начало работы", "Pierwsze kroki", "入门"],
        ["Налаштування ШІ", "AI setup", "Настройка ИИ", "Konfiguracja AI", "AI 设置"],
        ["Інтеграції", "Integrations", "Интеграции", "Integracje", "集成"],
        ["Голосовий ШІ", "Voice AI", "Голосовой ИИ", "Głosowe AI", "语音 AI"],
        ["Оплати", "Payments", "Оплаты", "Płatności", "付款"],
        ["Безпека", "Security", "Безопасность", "Bezpieczeństwo", "安全"],
        ["Вирішення проблем", "Troubleshooting", "Решение проблем", "Rozwiązywanie problemów", "故障排除"],
        ["Тарифи", "Pricing", "Тарифы", "Cennik", "价格"],

        ["SafeOrbit API Reference", "SafeOrbit API Reference", "Справочник SafeOrbit API", "Dokumentacja SafeOrbit API", "SafeOrbit API 参考"],
        ["Introduction", "Introduction", "Введение", "Wprowadzenie", "介绍"],
        ["Getting Started", "Getting started", "Начало работы", "Pierwsze kroki", "入门"],
        ["Authentication", "Authentication", "Аутентификация", "Uwierzytelnianie", "身份验证"],
        ["Quick Start", "Quick start", "Быстрый старт", "Szybki start", "快速开始"],
        ["API Reference", "API reference", "Справочник API", "Dokumentacja API", "API 参考"],
        ["Customers", "Customers", "Клиенты", "Klienci", "客户"],
        ["Appointments", "Appointments", "Записи", "Wizyty", "预约"],
        ["API Keys", "API keys", "API ключи", "Klucze API", "API 密钥"],
        ["Webhooks", "Webhooks", "Вебхуки", "Webhooki", "Webhook"],
        ["Chat API", "Chat API", "Chat API", "Chat API", "聊天 API"],
        ["Guides", "Guides", "Руководства", "Poradniki", "指南"],
        ["Errors", "Errors", "Ошибки", "Błędy", "错误"],
        ["Best Practices", "Best practices", "Лучшие практики", "Dobre praktyki", "最佳实践"],
        ["Copy", "Copy", "Копировать", "Kopiuj", "复制"],
        ["Copied!", "Copied!", "Скопировано!", "Skopiowano!", "已复制！"],
        ["Клієнти (Customers)", "Customers", "Клиенты", "Klienci", "客户"],
        ["Записи (Appointments)", "Appointments", "Записи", "Wizyty", "预约"],
        ["API Ключі (API Keys)", "API keys", "API ключи", "Klucze API", "API 密钥"],
        ["Вебхуки (Webhooks)", "Webhooks", "Вебхуки", "Webhooki", "Webhook"],
        ["Структура події (Payload)", "Event structure (payload)", "Структура события (payload)", "Struktura zdarzenia (payload)", "事件结构（payload）"],
        ["Доступні події", "Available events", "Доступные события", "Dostępne zdarzenia", "可用事件"],
        ["Валідація цифрового підпису (Python Example)", "Digital signature validation (Python example)", "Валидация цифровой подписи (пример Python)", "Walidacja podpisu cyfrowego (przykład Python)", "数字签名验证（Python 示例）"],
        ["Приклад інтеграції (Python)", "Integration example (Python)", "Пример интеграции (Python)", "Przykład integracji (Python)", "集成示例（Python）"],

        ["Чек №:", "Receipt no.:", "Чек №:", "Paragon nr:", "收据号："],
        ["Дата:", "Date:", "Дата:", "Data:", "日期："],
        ["Профіль гостя:", "Guest profile:", "Профиль гостя:", "Profil gościa:", "访客资料："],
        ["Касир:", "Cashier:", "Кассир:", "Kasjer:", "收银员："],
        ["Послуга:", "Service:", "Услуга:", "Usługa:", "服务："],
        ["СУМА ДО СПЛАТИ:", "AMOUNT DUE:", "СУММА К ОПЛАТЕ:", "DO ZAPŁATY:", "应付金额："],
        ["Дякуємо за візит!", "Thank you for your visit!", "Спасибо за визит!", "Dziękujemy za wizytę!", "感谢您的到访！"],
        ["Чекаємо на вас знову.", "We look forward to seeing you again.", "Ждем вас снова.", "Zapraszamy ponownie.", "期待再次见到您。"],
        ["Зберегти PDF / Друк", "Save PDF / Print", "Сохранить PDF / Печать", "Zapisz PDF / Drukuj", "保存 PDF / 打印"],
        ["Адреса не вказана", "Address not specified", "Адрес не указан", "Nie podano adresu", "未指定地址"],
        ["Система", "System", "Система", "System", "系统"],

        ["Сьог", "Today", "Сег", "Dziś", "今"],
        ["Зав", "Tom", "Зав", "Jut", "明"],
        ["Нд", "Sun", "Вс", "Nd", "日"],
        ["Пн", "Mon", "Пн", "Pn", "一"],
        ["Вв", "Tue", "Вт", "Wt", "二"],
        ["Ср", "Wed", "Ср", "Śr", "三"],
        ["Чт", "Thu", "Чт", "Cz", "四"],
        ["Пт", "Fri", "Пт", "Pt", "五"],
        ["Сб", "Sat", "Сб", "Sb", "六"],
    ].forEach((row) => add(row[0], row[1], row[2], row[3], row[4]));

    const prefixTranslations = [
        ["До сплати:", "Amount due:", "К оплате:", "Do zapłaty:", "应付金额："],
        ["Отримувач:", "Recipient:", "Получатель:", "Odbiorca:", "收款人："],
        ["Чек #", "Receipt #", "Чек #", "Paragon #", "收据 #"],
        ["Онлайн-запис |", "Online booking |", "Онлайн-запись |", "Rezerwacja online |", "在线预约 |"],
        ["Доставка:", "Delivery:", "Доставка:", "Dostawa:", "配送："],
    ].map((row) => ({ source: row[0], en: row[1], ru: row[2], pl: row[3], zh: row[4] }));

    const MACHINE_CACHE_KEY = "safeorbit.i18n.machineCache.v1";
    Object.entries(window.SafeOrbitLocaleCatalog || {}).forEach(([source, values]) => add(source, values.en, values.ru, values.pl, values.zh));
    const normalizedMaps = Object.fromEntries(Object.keys(translations).map(lang => [lang, Object.fromEntries(Object.entries(translations[lang]).map(([key,value]) => [key.normalize('NFKC').replace(/[’ʼ]/g, "'"),value]))]));
    const caseInsensitiveMaps = Object.fromEntries(Object.entries(normalizedMaps).map(([lang, entries]) => [
        lang, Object.fromEntries(Object.entries(entries).map(([key, value]) => [key.toLowerCase(), value])),
    ]));
    const textOriginals = new WeakMap();
    const machineCache = loadMachineCache();
    const pendingByLang = Object.create(null);
    let flushTimer = null;
    const ignoredSelector = [
        "script",
        "style",
        "code",
        "pre",
        "textarea",
        "[data-i18n-ignore]",
        ".so-i18n-switcher",
        ".msg-bubble",
        ".conv-name",
        ".search-result-title",
    ].join(",");

    function normalize(text) {
        return String(text || "").replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();
    }

    function splitOuterWhitespace(text) {
        const value = String(text || "");
        return {
            leading: (value.match(/^\s*/) || [""])[0],
            trailing: (value.match(/\s*$/) || [""])[0],
        };
    }

    function stripKnownSymbols(text) {
        return text.replace(/^[\u{1F300}-\u{1FAFF}\u2600-\u27BF]\uFE0F?\s*/u, "");
    }

    function translateText(sourceText, lang) {
        if (!lang || lang === "uk") return sourceText;

        const source = normalize(sourceText);
        if (!source) return sourceText;

        const exact = translations[lang] && translations[lang][source];
        if (exact) return exact;
        const normalized = source.normalize('NFKC').replace(/[’ʼ]/g, "'");
        if (normalizedMaps[lang]?.[normalized]) return normalizedMaps[lang][normalized];
        const insensitive = caseInsensitiveMaps[lang]?.[normalized.toLowerCase()];
        if (insensitive) return insensitive;
        const decoration = source.match(/^([←→↗✓✦✳▦♙⌁⚙+]*\s*)(.*?)(\s*[←→↗✓✦✳▦♙⌁⚙⌄:]*)(\s*)$/u);
        if (decoration && decoration[2] !== source) {
            const translated = normalizedMaps[lang]?.[decoration[2].normalize('NFKC').replace(/[’ʼ]/g, "'")];
            if (translated) return decoration[1] + translated + decoration[3] + decoration[4];
        }
        const quantity = source.match(/^(\d+(?:[.,]\d+)?)\s+шт\.$/u);
        if (quantity) return quantity[1] + " " + {en:"pcs", ru:"шт.", pl:"szt.", zh:"件"}[lang];
        const count = source.match(/^(\d+)\s+(записів|запису|клієнтів|візитів)$/u);
        if (count) return count[1] + ' ' + ({en:count[2] === 'клієнтів' ? 'customers' : 'appointments',ru:count[2] === 'клієнтів' ? 'клиентов' : 'записей',pl:count[2] === 'клієнтів' ? 'klientów' : 'wizyt',zh:count[2] === 'клієнтів' ? '客户' : '预约'}[lang]);


        const machine = MACHINE_TRANSLATION_ENABLED && machineCache[lang] && machineCache[lang][source];
        if (machine) return machine;

        const withoutSymbol = stripKnownSymbols(source);
        if (withoutSymbol !== source) {
            const plain = withoutSymbol.normalize("NFKC").replace(/[’ʼ]/g, "'");
            const known = normalizedMaps[lang]?.[plain] || caseInsensitiveMaps[lang]?.[plain.toLowerCase()];
            if (known) return source.slice(0, source.length - withoutSymbol.length) + known;
        }

        for (const item of prefixTranslations) {
            if (source.startsWith(item.source)) {
                const translatedPrefix = item[lang];
                if (translatedPrefix) {
                    return translatedPrefix + source.slice(item.source.length);
                }
            }
        }

        return sourceText;
    }

    function getStoredCurrency() {
        let stored;
        try { stored = localStorage.getItem(CURRENCY_STORAGE_KEY); } catch (_) {}
        return CURRENCIES[stored] ? stored : "UAH";
    }

    function formatCurrencyFromUah(amountUah, currencyCode, suffix) {
        const currency = CURRENCIES[currencyCode] || CURRENCIES.UAH;
        const converted = currencyCode === "UAH" ? amountUah : amountUah / currency.rate;
        const hasCents = Math.abs(converted) > 0 && Math.abs(converted) < 100;
        const formattedNumber = new Intl.NumberFormat(currency.locale, {
            minimumFractionDigits: hasCents ? 2 : 0,
            maximumFractionDigits: hasCents ? 2 : 0,
        }).format(converted);
        const normalizedSuffix = suffix || "";

        if (currencyCode === "UAH") return `${formattedNumber} ₴${normalizedSuffix}`;
        if (currencyCode === "PLN") return `${formattedNumber} ${currency.symbol}${normalizedSuffix}`;
        return `${currency.symbol}${formattedNumber}${normalizedSuffix}`;
    }

    function convertCurrencyText(text, currencyCode) {
        if (!text || currencyCode === "UAH") return text;
        return String(text).replace(/(\d[\d\s.,]*)(?:\s*)(₴|грн)(\s*\/\s*(?:міс|month|mo|місяць|месяц))?/gi, (match, rawAmount, _unit, suffix) => {
            const normalized = rawAmount.replace(/\s/g, "").replace(",", ".");
            const amount = Number.parseFloat(normalized);
            if (!Number.isFinite(amount)) return match;
            return formatCurrencyFromUah(amount, currencyCode, suffix || "");
        });
    }

    function loadMachineCache() {
        try {
            const parsed = JSON.parse(localStorage.getItem(MACHINE_CACHE_KEY) || "{}");
            return parsed && typeof parsed === "object" ? parsed : {};
        } catch (_) {
            return {};
        }
    }

    function saveMachineCache() {
        try {
            localStorage.setItem(MACHINE_CACHE_KEY, JSON.stringify(machineCache));
        } catch (_) {
            // Local storage can be full or disabled; translations still work for this page load.
        }
    }

    function shouldMachineTranslate(sourceText, lang) {
        if (!MACHINE_TRANSLATION_ENABLED) return false;
        if (!lang || lang === "uk") return false;
        const source = normalize(sourceText);
        if (!source || source.length > 1000) return false;
        if (translations[lang] && translations[lang][source]) return false;
        if (machineCache[lang] && machineCache[lang][source]) return false;
        if (/^(https?:\/\/|\/static\/|sk_live_|[A-Z]{2}\d{8,})/i.test(source)) return false;
        if (!/[A-Za-zА-Яа-яІіЇїЄєҐґ]/.test(source)) return false;
        return true;
    }

    function queueMachineTranslation(sourceText, lang) {
        const source = normalize(sourceText);
        if (!shouldMachineTranslate(source, lang)) return;

        if (!pendingByLang[lang]) pendingByLang[lang] = new Set();
        pendingByLang[lang].add(source);

        clearTimeout(flushTimer);
        flushTimer = setTimeout(flushMachineTranslations, 180);
    }

    async function flushMachineTranslations() {
        const jobs = Object.entries(pendingByLang)
            .map(([lang, values]) => [lang, Array.from(values)])
            .filter(([, values]) => values.length > 0);

        Object.keys(pendingByLang).forEach((lang) => pendingByLang[lang].clear());
        if (!jobs.length) return;

        for (const [lang, values] of jobs) {
            for (let i = 0; i < values.length; i += 40) {
                const chunk = values.slice(i, i + 40);
                try {
                    const response = await fetch("/api/i18n/translate", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ target: lang, texts: chunk }),
                    });
                    if (!response.ok) continue;

                    const payload = await response.json();
                    const received = payload.translations || {};
                    if (!machineCache[lang]) machineCache[lang] = {};

                    Object.entries(received).forEach(([source, translated]) => {
                        if (translated && translated !== source) {
                            machineCache[lang][source] = translated;
                        }
                    });
                    saveMachineCache();

                    if (getStoredLanguage() === lang) {
                        translateTree(document.body || document.documentElement, lang);
                        translateTitle(lang);
                    }
                } catch (_) {
                    // Network translation is best-effort. Known dictionary strings still translate.
                }
            }
        }
    }

    function shouldIgnoreElement(element) {
        return !element || element.nodeType !== 1 || Boolean(element.closest(ignoredSelector));
    }

    function translateTextNode(node, lang) {
        const parent = node.parentElement;
        if (shouldIgnoreElement(parent)) return;
        if (parent.tagName === "OPTION" && !parent.hasAttribute("value")) {
            parent.value = parent.value;
        }

        if (!textOriginals.has(node)) {
            textOriginals.set(node, node.nodeValue);
        }

        let original = textOriginals.get(node);
        if (node.safeorbitRenderedText !== undefined && node.nodeValue !== node.safeorbitRenderedText) {
            original = node.nodeValue;
            textOriginals.set(node, original);
        }
        const translated = convertCurrencyText(translateText(original, lang), getStoredCurrency());
        queueMachineTranslation(original, lang);
        const whitespace = splitOuterWhitespace(original);
        const nextValue = translated === original ? original : whitespace.leading + translated.trim() + whitespace.trailing;
        node.safeorbitRenderedText = nextValue;
        if (node.nodeValue !== nextValue) {
            node.nodeValue = nextValue;
        }
    }

    function translateAttribute(element, attribute, lang) {
        if (shouldIgnoreElement(element) || !element.hasAttribute(attribute)) return;

        const dataName = "i18nOriginal" + attribute.replace(/(^|-)([a-z])/g, (_, __, char) => char.toUpperCase());
        if (!element.dataset[dataName]) {
            element.dataset[dataName] = element.getAttribute(attribute) || "";
        }

        const renderedName = "safeorbitRendered" + attribute;
        if (element[renderedName] !== undefined && element.getAttribute(attribute) !== element[renderedName]) {
            element.dataset[dataName] = element.getAttribute(attribute) || "";
        }
        const original = element.dataset[dataName];
        const translated = convertCurrencyText(translateText(original, lang), getStoredCurrency());
        queueMachineTranslation(original, lang);
        element[renderedName] = translated;
        if (translated !== element.getAttribute(attribute)) {
            element.setAttribute(attribute, translated);
        }
    }

    function translateElementAttributes(root, lang) {
        const elements = root.nodeType === 1 ? [root, ...root.querySelectorAll("[placeholder], [title], [aria-label], input[type='button'], input[type='submit'], input[type='reset']")] : [];
        for (const element of elements) {
            translateAttribute(element, "placeholder", lang);
            translateAttribute(element, "title", lang);
            translateAttribute(element, "aria-label", lang);
            if (element.matches("input[type='button'], input[type='submit'], input[type='reset']")) {
                translateAttribute(element, "value", lang);
            }
        }
    }

    function translateTree(root, lang) {
        if (!root) return;

        translateElementAttributes(root, lang);

        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
                if (!normalize(node.nodeValue)) return NodeFilter.FILTER_REJECT;
                if (shouldIgnoreElement(node.parentElement)) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            },
        });

        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach((node) => translateTextNode(node, lang));
    }

    let originalTitle = "";

    function translateTitle(lang) {
        if (!originalTitle) originalTitle = document.title || "";
        if (!originalTitle) return;

        const direct = convertCurrencyText(translateText(originalTitle, lang), getStoredCurrency());
        queueMachineTranslation(originalTitle, lang);
        if (direct !== originalTitle) {
            document.title = direct;
            return;
        }

        const separator = " | ";
        if (originalTitle.includes(separator)) {
            const parts = originalTitle.split(separator);
            const originalFirstPart = parts[0];
            parts[0] = convertCurrencyText(translateText(originalFirstPart, lang), getStoredCurrency());
            queueMachineTranslation(originalFirstPart, lang);
            document.title = parts.join(separator);
        }
    }

    let activeLanguage;
    function getStoredLanguage() {
        if (activeLanguage) return activeLanguage;
        let stored;
        try { stored = localStorage.getItem(STORAGE_KEY); } catch (_) {}
        stored ||= document.cookie.match(/(?:^|; )safeorbit_lang=([a-z]+)/)?.[1];
        return SUPPORTED[stored] ? stored : "uk";
    }

    function writeLanguageCookie(lang) {
        document.cookie = "safeorbit_lang=" + encodeURIComponent(lang) + "; path=/; max-age=31536000; SameSite=Lax";
    }

    function applyLanguage(lang) {
        const safeLang = SUPPORTED[lang] ? lang : "uk";
        activeLanguage = safeLang;
        try { localStorage.setItem(STORAGE_KEY, safeLang); } catch (_) {}
        writeLanguageCookie(safeLang);
        document.documentElement.lang = SUPPORTED[safeLang].htmlLang;

        document.querySelectorAll("[data-language-select]").forEach(select => {
            if (select.value !== safeLang) select.value = safeLang;
        });
        const currencySelect = document.getElementById("safeorbit-currency-select");
        if (currencySelect && currencySelect.value !== getStoredCurrency()) {
            currencySelect.value = getStoredCurrency();
        }

        translateTree(document.body || document.documentElement, safeLang);
        translateTitle(safeLang);

        window.dispatchEvent(new CustomEvent("safeorbit:language-changed", { detail: { language: safeLang } }));
    }

    function applyCurrency(currencyCode) {
        const safeCurrency = CURRENCIES[currencyCode] ? currencyCode : "UAH";
        try { localStorage.setItem(CURRENCY_STORAGE_KEY, safeCurrency); } catch (_) {}
        const select = document.getElementById("safeorbit-currency-select");
        if (select && select.value !== safeCurrency) select.value = safeCurrency;
        applyLanguage(getStoredLanguage());
        window.dispatchEvent(new CustomEvent("safeorbit:currency-changed", { detail: { currency: safeCurrency } }));
    }

    function injectStyles() {
        if (document.getElementById("safeorbit-i18n-styles")) return;
        const style = document.createElement("style");
        style.id = "safeorbit-i18n-styles";
        style.textContent = `
            .so-i18n-switcher {
                display: inline-flex;
                align-items: center;
                gap: 10px;
                color: #fff;
                flex-shrink: 0;
                padding: 6px;
                border-radius: 22px;
                background: rgba(15, 23, 42, 0.42);
                border: 1px solid rgba(187, 134, 252, 0.18);
                box-shadow: 0 16px 40px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255,255,255,0.08);
                backdrop-filter: blur(18px);
                -webkit-backdrop-filter: blur(18px);
            }
            .so-i18n-switcher.so-i18n-floating {
                position: fixed;
                top: max(14px, env(safe-area-inset-top));
                right: max(14px, env(safe-area-inset-right));
                z-index: 2147483000;
            }
            .so-pref-field {
                display: inline-flex;
                align-items: center;
                gap: 7px;
                min-width: 0;
            }
            .so-i18n-switcher .so-i18n-icon {
                width: 32px;
                height: 32px;
                border-radius: 14px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                background: linear-gradient(135deg, rgba(187,134,252,0.18), rgba(96,165,250,0.10));
                border: 1px solid rgba(255, 255, 255, 0.12);
                color: rgba(255,255,255,0.78);
            }
            .so-i18n-select,
            .so-currency-select {
                height: 38px;
                min-width: 94px;
                border-radius: 16px;
                border: 1px solid rgba(255, 255, 255, 0.10);
                background: rgba(255, 255, 255, 0.04);
                color: #fff;
                padding: 0 12px;
                font: 700 13px/1.2 Manrope, Inter, system-ui, -apple-system, Segoe UI, sans-serif;
                outline: none;
                transition: border-color .2s ease, background .2s ease, box-shadow .2s ease;
            }
            .so-currency-select {
                min-width: 82px;
            }
            .so-i18n-select:focus,
            .so-currency-select:focus {
                border-color: rgba(187, 134, 252, 0.78);
                background: rgba(255, 255, 255, 0.075);
                box-shadow: 0 0 0 3px rgba(187, 134, 252, 0.16);
            }
            .so-i18n-select option,
            .so-currency-select option {
                background: #111827;
                color: #fff;
            }
            .top-header .so-i18n-switcher {
                margin-left: 0;
            }
            @media (max-width: 767.98px) {
                .so-i18n-switcher.so-i18n-floating {
                    top: 10px;
                    right: 10px;
                }
                .so-i18n-switcher .so-i18n-icon {
                    display: none;
                }
                .so-i18n-select,
                .so-currency-select {
                    min-width: 76px;
                    height: 34px;
                    font-size: 12px;
                }
            }
        `;
        document.head.appendChild(style);
    }

    function createSwitcher() {
        if (document.getElementById("safeorbit-language-select")) return;

        const wrap = document.createElement("div");
        wrap.className = "so-i18n-switcher";
        wrap.setAttribute("data-i18n-ignore", "true");

        const currencyField = document.createElement("span");
        currencyField.className = "so-pref-field";
        const currencyIcon = document.createElement("span");
        currencyIcon.className = "so-i18n-icon";
        currencyIcon.setAttribute("aria-hidden", "true");
        currencyIcon.innerHTML = '<i class="fas fa-coins"></i>';
        const currencySelect = document.createElement("select");
        currencySelect.id = "safeorbit-currency-select";
        currencySelect.className = "so-currency-select";
        currencySelect.setAttribute("aria-label", "Currency");

        Object.keys(CURRENCIES).forEach((code) => {
            const option = document.createElement("option");
            option.value = code;
            option.textContent = `${CURRENCIES[code].symbol} ${code}`;
            currencySelect.appendChild(option);
        });
        currencySelect.value = getStoredCurrency();
        currencySelect.addEventListener("change", () => applyCurrency(currencySelect.value));
        currencyField.appendChild(currencyIcon);
        currencyField.appendChild(currencySelect);

        const languageField = document.createElement("span");
        languageField.className = "so-pref-field";
        const icon = document.createElement("span");
        icon.className = "so-i18n-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.innerHTML = '<i class="fas fa-language"></i>';

        const select = document.createElement("select");
        select.id = "safeorbit-language-select";
        select.dataset.languageSelect = "";
        select.className = "so-i18n-select";
        select.setAttribute("aria-label", "Language");

        Object.keys(SUPPORTED).forEach((code) => {
            const option = document.createElement("option");
            option.value = code;
            option.textContent = SUPPORTED[code].label;
            select.appendChild(option);
        });

        select.value = getStoredLanguage();
        select.addEventListener("change", () => applyLanguage(select.value));

        languageField.appendChild(icon);
        languageField.appendChild(select);

        wrap.appendChild(currencyField);
        wrap.appendChild(languageField);

        const headerActions = document.querySelector(".topbar-right") || document.querySelector(".top-header > div:last-child");
        if (headerActions) {
            const userPill = headerActions.querySelector(".user-pill");
            headerActions.insertBefore(wrap, userPill || null);
        } else {
            wrap.classList.add("so-i18n-floating");
            document.body.appendChild(wrap);
        }
    }

    function startObserver() {
        const observer = new MutationObserver((mutations) => {
            const lang = getStoredLanguage();
            for (const mutation of mutations) {
                if (mutation.type === "characterData") {
                    translateTextNode(mutation.target, lang);
                    continue;
                }
                if (mutation.type === "attributes") {
                    translateAttribute(mutation.target, mutation.attributeName, lang);
                    continue;
                }
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === 3) translateTextNode(node, lang);
                    if (node.nodeType === 1) translateTree(node, lang);
                });
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true,
            attributeFilter: ["placeholder", "title", "aria-label", "value"],
        });
    }

    function init() {
        injectStyles();
        if (!document.querySelector('[data-language-select]')) createSwitcher();
        document.querySelectorAll('[data-language-select]').forEach(select => {
            select.value = getStoredLanguage(); select.addEventListener('change', () => applyLanguage(select.value));
        });
        applyLanguage(getStoredLanguage());
        startObserver();
    }

    window.addEventListener("storage", event => {
        if (event.key === STORAGE_KEY && SUPPORTED[event.newValue]) applyLanguage(event.newValue);
    });

    window.SafeOrbitI18N = {
        translate: (value) => translateText(String(value), getStoredLanguage()),
        setLanguage: applyLanguage,
        getLanguage: getStoredLanguage,
        apply: () => applyLanguage(getStoredLanguage()),
        supported: SUPPORTED,
        setCurrency: applyCurrency,
        getCurrency: getStoredCurrency,
        currencies: CURRENCIES,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
