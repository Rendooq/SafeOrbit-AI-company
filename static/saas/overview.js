(() => {
  "use strict";
  const board = document.querySelector(".dayboard");
  if (!board) return;

  const message = {
    fields: "Перевірте дату, час, назву послуги й суму запису.",
    permission: "Недостатньо прав для цієї дії.",
    master: "Спеціаліст недоступний або належить іншому бізнесу.",
  }[new URLSearchParams(location.search).get("error")];
  if (message) {
    const alert = document.createElement("p");
    alert.className = "alert alert-warning";
    alert.setAttribute("role","alert");
    alert.textContent = window.SafeOrbitI18N?.translate(message) || message;
    board.prepend(alert);
  }

  const source = document.getElementById("overview-chart-data");
  const canvas = document.getElementById("overview-revenue-chart");
  if (source && canvas && window.Chart) {
    const data = JSON.parse(source.textContent);
    const colors = getComputedStyle(board);
    const ink = () => colors.getPropertyValue("--board-purple").trim() || "#594196";
    const wash = () => colors.getPropertyValue("--board-lilac").trim() || "#eee8f8";
    const color = colors.getPropertyValue("--board-muted").trim();
    const series = {data: data.values, borderColor: ink(), backgroundColor: wash(), fill: true,
      borderWidth: 2, pointRadius: data.labels.length > 7 ? 0 : 2, pointHitRadius: 9, tension: .23};
    const chart = new Chart(canvas, {
      type: "line", data: {labels: data.labels,datasets: [series]},
      options: {responsive: true, maintainAspectRatio: false, animation: false,
        plugins: {legend: {display: false}, tooltip: {displayColors: false, callbacks: {
          label: point => point.parsed.y.toLocaleString(document.documentElement.lang) + " ₴"
        }}},
        scales: {x: {grid: {display: false}, ticks: {color, maxRotation: 0, maxTicksLimit: 5}},
          y: {beginAtZero: true, suggestedMax: data.values.some(Boolean) ? undefined : 1,
            grid: {color: colors.getPropertyValue("--board-line").trim()}, ticks: {color, maxTicksLimit: 4}}}
      }
    });
    window.addEventListener("safeorbit:themechange", () => {
      series.borderColor = ink();
      series.backgroundColor = wash();
      chart.update("none");
    });
  }

  const legacy = document.getElementById("legacy-workspace-content");
  const target = document.getElementById("legacy-tools");
  if (!legacy || !target) return;
  target.append(legacy);
  legacy.hidden = false;
  const tools = target.closest("details");
  const form = legacy.querySelector('form[action="/admin/add-appointment"]');
  legacy.querySelectorAll(".modal").forEach(modal => document.body.append(modal));
  document.querySelectorAll("[data-legacy-edit],[data-agenda-edit]").forEach(button => {
    button.addEventListener("click", () => {
      window.editApp(...JSON.parse(button.dataset.agendaEdit || button.dataset.editArgs));
    });
  });

  function openCalendar() {
    tools.open = true;
    const calendarTab = legacy.querySelector('[data-bs-target="#tab-calendar"]');
    calendarTab?.click();
    if (calendarTab) calendarTab.focus({preventScroll: true});
  }
  function openAppointment() {
    tools.open = true;
    legacy.querySelector('[data-bs-target="#tab-list"]')?.click();
    if (!form) return;
    form.elements.date.value = board.dataset.selectedDay;
    const staff = form.elements.master_id;
    if (staff instanceof HTMLSelectElement && board.dataset.selectedMaster !== "0") {
      staff.value = board.dataset.selectedMaster;
    }
    form.scrollIntoView({block: "center"});
    form.querySelector('input:not([type="hidden"]),select')?.focus({preventScroll: true});
  }

  if (form) form.id = "new-appointment";
  for (const link of document.querySelectorAll("[data-create-shortcut]")) {
    link.addEventListener("click", event => { event.preventDefault(); openAppointment(); });
  }
  for (const link of document.querySelectorAll("[data-calendar-shortcut]")) {
    link.addEventListener("click", event => {
      event.preventDefault();
      openCalendar();
      tools.scrollIntoView({block: "start"});
    });
  }
  // The older toolbar also contains a create button. It shares the same form.
  legacy.querySelectorAll('[data-bs-target="#addAppt"]').forEach(button => {
    button.removeAttribute("data-bs-toggle");
    button.removeAttribute("data-bs-target");
    button.addEventListener("click", openAppointment);
  });
  function openAnchor() {
    if (location.hash === "#calendar") openCalendar();
    if (location.hash === "#new-appointment") openAppointment();
  }
  window.addEventListener("hashchange", openAnchor);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", openAnchor);
  else openAnchor();
  tools.addEventListener("toggle", () => { if (tools.open) window.dispatchEvent(new Event("resize")); });
})();
