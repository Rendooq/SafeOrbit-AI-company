import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { findOpenings, parseSchedule } from '../static/v2/schedule-audit.mjs';

const example = readFileSync(new URL('../static/templates/rozklad-salonu.csv', import.meta.url), 'utf8');
const header = example.split('\n')[0];

test('the example finds free time around booked visits and matches cancellations', () => {
  const shifts = parseSchedule(`\uFEFF${example.replaceAll('\n', '\r\n')}`);
  const openings = findOpenings(shifts, 60, 0);
  assert.deepEqual(openings.map(window => [window.start, window.end, window.cancelled]), [
    [780, 870, true], [930, 1020, false], [720, 795, true], [960, 1020, false],
  ]);
  assert.deepEqual(openings[0].matches, [['Запит 2', 780], ['Запит 1', 795]]);
  assert.deepEqual(openings[2].matches, [['Запит 3', 720]]);
  assert.equal(findOpenings(shifts, 60, 16).length, 2);
});

test('overlapping visits only block the combined time and other masters remain independent', () => {
  const shifts = parseSchedule(`${header}
2026-12-01;А;09:00;17:00;08:00;11:00;запис;
2026-12-01;А;09:00;17:00;10:00;13:00;запис;
2026-12-01;А;09:00;17:00;12:00;13:00;скасовано;
2026-12-01;А;09:00;17:00;14:00;16:00;запис;
2026-12-01;Б;09:00;17:00;;;зміна;`);
  assert.deepEqual(findOpenings(shifts, 60, 1).map(window => [window.specialist, window.start, window.end]), [
    ['Б', 540, 1020],
  ]);
  assert.ok(findOpenings(shifts, 60, 0).every(window => !window.cancelled));
});

test('CSV accepts quoted fields and rejects inconsistent shifts and impossible dates', () => {
  const fields = header.replaceAll(';', ',');
  const row = '2026-12-01,"Майстер, А",09:00,17:00,,,зміна,';
  assert.equal(parseSchedule(`${fields}\n${row}`)[0].specialist, 'Майстер, А');
  const localized = row.replace('2026-12-01', '01.12.2026').replace('09:00', '9:00:00');
  assert.deepEqual(parseSchedule(`${fields}\n${localized}`), parseSchedule(`${fields}\n${row}`));
  assert.throws(() => parseSchedule(`${fields}\n${row}\n${row.replace('09:00', '10:00')}`), /години зміни/);
  assert.throws(() => parseSchedule(`${fields}\n${row.replace('2026-12-01', '2026-02-30')}`), /перевірте дату/);
});
