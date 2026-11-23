(() => {
  "use strict";
  const source = document.getElementById("overview-chart-data");
  const canvas = document.getElementById("overview-revenue-chart");
  const errorCode = new URLSearchParams(location.search).get("error");
  const errors = {
    fields: "Перевірте дату, час, назву послуги й суму запису.",
    permission: "Недостатньо прав для цієї дії.",
    master: "Спеціаліст недоступний або належить іншому бізнесу.",
  };
  if (errors[errorCode]) {
    const alert = document.createElement("div"); alert.className = "alert alert-warning";
    alert.setAttribute("role","alert"); alert.textContent = errors[errorCode];
    document.querySelector(".workspace-content")?.prepend(alert);
  }
  if (source && canvas && window.Chart) {
    const data = JSON.parse(source.textContent);
    Chart.defaults.font.family = 'Manrope, "Segoe UI", Arial, sans-serif';
    const themeColors = getComputedStyle(document.documentElement);
    Chart.defaults.color = themeColors.getPropertyValue("--ui-muted").trim() || "#5b6373";
    new Chart(canvas, {
      type: "line",
      data: { labels: data.labels, datasets: [{ data: data.values, borderColor: "#ff6037", backgroundColor: "#ff603712", fill: true, borderWidth: 2, pointRadius: 2, pointHoverRadius: 4, pointBackgroundColor: "#ff6037", tension: .35 }] },
      options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { backgroundColor: "#252532", padding: 10, displayColors: false, callbacks: { label: context => `${context.parsed.y.toLocaleString("uk-UA")} ₴` } } }, scales: { x: { grid: { display: false }, border: { display: false }, ticks: { font: { size: 9 }, maxRotation: 0 } }, y: { beginAtZero: true, border: { display: false }, grid: { color: themeColors.getPropertyValue("--ui-border").trim() || "#d9dce5" }, ticks: { font: { size: 9 }, maxTicksLimit: 4 } } } }
    });
  }
  const legacy = document.getElementById("legacy-workspace-content");
  const target = document.getElementById("legacy-tools");
  if (legacy && target) { target.append(legacy); legacy.hidden = false; }
  const tools = document.querySelector(".overview-tools");
  const form = legacy?.querySelector('form[action="/admin/add-appointment"]');
  const openAppointment = () => {
    if (tools) tools.open = true;
    const listTab = legacy?.querySelector('[data-bs-target="#tab-list"]');
    listTab?.click();
    form?.scrollIntoView({behavior:"smooth",block:"center"});
    form?.querySelector("select,input")?.focus({preventScroll:true});
  };
  document.querySelectorAll('[data-bs-target="#addAppt"]').forEach(button => {
    button.removeAttribute("data-bs-toggle");
    button.removeAttribute("data-bs-target");
    button.addEventListener("click", openAppointment);
  });
  // Bootstrap modals cannot render inside a collapsed details ancestor.
  legacy?.querySelectorAll(".modal").forEach(modal => document.body.append(modal));
  document.querySelectorAll("[data-legacy-edit]").forEach(button => {
    button.addEventListener("click", () => {
      if (typeof window.editApp === "function") window.editApp(...JSON.parse(button.dataset.editArgs));
    });
  });
  document.querySelectorAll("[data-edit-appointment]").forEach(button => {
    button.addEventListener("click", () => {
      const original = document.querySelector(`[data-legacy-edit="${button.dataset.editAppointment}"]`);
      original?.click();
    });
  });
  tools?.addEventListener("toggle", () => {
    if (tools.open) window.dispatchEvent(new Event("resize"));
  });
})();
