const COLUMNS = ['Дата', 'Майстер', 'Початок зміни', 'Кінець зміни', 'Початок', 'Кінець', 'Статус', 'Псевдонім'];
const PROGRAM = '/static/templates/rozklad-salonu.csv';
const MAX_BYTES = 512 * 1024;
const MAX_ROWS = 1500;

function csvRows(text) {
  const source = text.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
  const header = source.trimStart().split('\n', 1)[0];
  const separator = header.includes(';') ? ';' : ',';
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  let closedQuote = false;

  const endField = () => {
    row.push(field.trim());
    field = '';
    closedQuote = false;
  };

  for (let index = 0; index <= source.length; index++) {
    const char = source[index] ?? '\n';
    if (quoted) {
      if (char !== '"') field += char;
      else if (source[index + 1] === '"') {
        field += '"';
        index++;
      } else {
        quoted = false;
        closedQuote = true;
      }
    } else if (char === separator || char === '\n') {
      endField();
      if (char === '\n') {
        if (row.some(Boolean)) rows.push(row);
        if (rows.length > MAX_ROWS + 1) throw new Error(`Файл має містити до ${MAX_ROWS} рядків даних.`);
        row = [];
      }
    } else if (char === '"' && !field && !closedQuote) {
      quoted = true;
    } else if (char === '"' || (closedQuote && char.trim())) {
      throw new Error('У CSV є поле з некоректними лапками. Перевірте формат і збережіть файл ще раз.');
    } else if (!closedQuote) {
      field += char;
    }
  }
  if (quoted) throw new Error('У CSV є незакриті лапки. Перевірте формат і збережіть файл ще раз.');
  return rows;
}

function minutes(value) {
  const parts = /^(\d|[01]\d|2[0-3]):([0-5]\d)(?::00)?$/.exec(value);
  return parts ? Number(parts[1]) * 60 + Number(parts[2]) : value === '24:00' ? 1440 : NaN;
}

function parseDate(value) {
  value = value.replace(/^(\d{2})\.(\d{2})\.(\d{4})$/, '$3-$2-$1');
  const date = new Date(`${value}T00:00:00Z`);
  if (/^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(+date) && date.toISOString().slice(0, 10) === value) return value;
  return '';
}

export function parseSchedule(text) {
  const [header, ...rows] = csvRows(text);
  const fields = COLUMNS.map(column => header?.indexOf(column) ?? -1);
  if (fields.some(index => index < 0) || new Set(header).size !== header.length) {
    throw new Error('Не вдалося розпізнати колонки. Скопіюйте заголовки з прикладу CSV.');
  }
  if (!rows.length) throw new Error('Додайте хоча б один запис або зміну.');

  const shifts = new Map();
  for (const [index, row] of rows.entries()) {
    const invalid = problem => new Error(`Запис ${index + 1} у файлі: ${problem}`);
    const [rawDate, specialist, shiftStart, shiftEnd, from, to, status, alias] = fields.map(field => row[field] ?? '');
    const date = parseDate(rawDate);
    const start = minutes(shiftStart);
    const end = minutes(shiftEnd);
    const kind = status.toLowerCase();
    if (row.length !== header.length) throw invalid('кількість полів не збігається із заголовками.');
    if (!date || !specialist || specialist.length > 80) throw invalid('перевірте дату й позначення майстра.');
    if (!(start < end)) throw invalid('перевірте початок і кінець зміни у форматі ГГ:ХХ.');
    if (!['запис', 'скасовано', 'очікує', 'зміна'].includes(kind)) throw invalid('невідомий статус.');
    const key = `${date}\n${specialist}`;
    const shift = shifts.get(key) ?? { date, specialist, start, end, booked: [], cancelled: [], waiting: [] };
    if (shift.start !== start || shift.end !== end) throw invalid('години зміни цього майстра відрізняються в межах дня.');
    shifts.set(key, shift);

    if (kind === 'зміна') {
      if (from || to) throw invalid('для статусу «зміна» залиште час візиту порожнім.');
      continue;
    }
    const period = { start: minutes(from), end: minutes(to) };
    if (!(period.start < period.end)) throw invalid('перевірте початок і кінець візиту у форматі ГГ:ХХ.');
    if (kind === 'очікує' && !alias) throw invalid('додайте псевдонім для списку очікування.');
    if (alias.length > 80) throw invalid('псевдонім має містити до 80 символів.');
    if (kind === 'запис') shift.booked.push(period);
    if (kind === 'скасовано') shift.cancelled.push(period);
    if (kind === 'очікує') shift.waiting.push({ ...period, alias });
  }
  return [...shifts.values()].sort((a, b) => a.date.localeCompare(b.date) || a.specialist.localeCompare(b.specialist, 'uk'));
}

const overlaps = (a, b) => a.start < b.end && b.start < a.end;

export function findOpenings(shifts, duration, buffer) {
  const windows = [];
  for (const shift of shifts) {
    const addWindow = (start, end) => {
      const length = end - start;
      if (length < duration + buffer) return;
      const cancellation = shift.cancelled.filter(period => overlaps({ start, end }, period));
      const matches = new Map();
      for (const waiting of shift.waiting) {
        const time = Math.max(start, waiting.start);
        const latest = Math.min(waiting.end - duration, end - duration - buffer);
        if (time > latest) continue;
        for (const released of cancellation) {
          const candidate = Math.max(time, Math.min(released.start, latest));
          if (!overlaps({ start: candidate, end: candidate + duration }, released)) continue;
          if (!matches.has(waiting.alias) || candidate < matches.get(waiting.alias)) matches.set(waiting.alias, candidate);
        }
      }
      windows.push({ date: shift.date, specialist: shift.specialist, start, end, length,
        cancelled: cancellation.length > 0,
        matches: [...matches].sort((a, b) => a[1] - b[1]),
      });
    };

    let cursor = shift.start;
    for (const busy of [...shift.booked].sort((a, b) => a.start - b.start)) {
      if (busy.end <= cursor) continue;
      addWindow(cursor, Math.min(busy.start, shift.end));
      cursor = Math.max(cursor, busy.end);
      if (cursor >= shift.end) break;
    }
    addWindow(cursor, shift.end);
  }
  return windows;
}

const showTime = value => `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
const showDate = new Intl.DateTimeFormat('uk-UA', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });

function renderWindow(window) {
  const row = document.createElement('li');
  const title = document.createElement('strong');
  const details = document.createElement('span');
  title.textContent = `${showTime(window.start)}–${showTime(window.end)} · ${window.length} хв`;
  details.textContent = `${showDate.format(new Date(`${window.date}T00:00:00Z`))} · ${window.specialist}`;
  row.append(title, details);
  if (window.cancelled) {
    const tag = document.createElement('span');
    tag.className = 'audit-tag';
    tag.textContent = 'Після скасування';
    row.append(tag);
  }
  if (window.matches.length) {
    const list = document.createElement('ul');
    for (const [alias, time] of window.matches) {
      const item = document.createElement('li');
      item.textContent = `${alias} · можна запропонувати ${showTime(time)}`;
      list.append(item);
    }
    row.append(list);
  }
  return row;
}

function initAudit() {
  const get = id => document.getElementById(`audit-${id}`);
  const form = get('options');
  const file = get('file');
  const example = get('example');
  const message = get('message');
  const filter = get('cancelled');
  let shifts;
  let version = 0;

  const render = () => {
    if (!shifts) return;
    if (!form.reportValidity()) {
      get('filter').hidden = true;
      get('data').hidden = true;
      get('empty').hidden = false;
      get('empty').textContent = 'Перевірте тривалість і перерву, а тоді запустіть розбір.';
      return;
    }
    const windows = findOpenings(shifts, get('duration').valueAsNumber, get('buffer').valueAsNumber);
    const released = windows.filter(window => window.cancelled);
    const visible = filter.checked ? released : windows;
    get('empty').hidden = true;
    get('filter').hidden = false;
    get('data').hidden = false;
    get('count').textContent = windows.length;
    get('released').textContent = released.length;
    get('matches').textContent = released.reduce((count, window) => count + window.matches.length, 0);
    get('results-note').textContent = visible.length
      ? `Вікон у вибірці — ${visible.length}. Збіги зі списком очікування — варіанти для пропозиції.`
      : 'У цій вибірці немає вікон потрібної тривалості.';
    get('windows').replaceChildren(...visible.map(renderWindow));
  };

  async function load(read, label) {
    const current = ++version;
    message.textContent = 'Читаємо розклад…';
    message.classList.remove('audit-error');
    try {
      const next = parseSchedule(await read());
      if (current !== version) return;
      shifts = next;
      filter.checked = false;
      get('source').textContent = label;
      message.textContent = '';
      render();
    } catch (error) {
      if (current !== version) return;
      message.classList.add('audit-error');
      message.textContent = error.message;
    }
  }

  file.addEventListener('change', () => {
    const selected = file.files[0];
    if (!selected) return;
    file.value = '';
    load(async () => {
      if (selected.size > MAX_BYTES) throw new Error('Виберіть файл CSV розміром до 512 КБ.');
      return selected.text();
    }, 'Ваш розклад із CSV');
  });
  example.addEventListener('click', () => load(async () => {
    const response = await fetch(PROGRAM);
    if (!response.ok) throw new Error('Приклад не відкрився. Спробуйте ще раз.');
    return response.text();
  }, 'Демонстраційний розклад'));
  form.addEventListener('submit', event => {
    event.preventDefault();
    render();
  });
  filter.addEventListener('change', render);
  get('tool').hidden = false;
  example.click();
}

if (typeof document !== 'undefined' && document.getElementById('audit-tool')) initAudit();
