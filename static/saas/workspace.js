(() => {
  "use strict";
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-customer-edit]');
    if (button && typeof window.editCustomer === 'function') window.editCustomer(...JSON.parse(button.dataset.customerEdit));
  });
  const safeCalls = new Set(['openPaymentModal','editPaymentSettings','editBiz','resetPass','createMasterAccount','showApiKeyLogs']);
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-safe-call]');
    if (button && safeCalls.has(button.dataset.safeCall) && typeof window[button.dataset.safeCall] === 'function')
      window[button.dataset.safeCall](...JSON.parse(button.dataset.safeArgs));
  });
  const sidebar = document.getElementById("workspace-sidebar");
  const overlay = document.getElementById("workspace-overlay");
  const toggle = document.getElementById("workspace-menu-toggle");
  const closeMenu = () => { sidebar?.classList.remove("mobile-open"); overlay?.classList.remove("open"); toggle?.setAttribute("aria-expanded", "false"); };
  toggle?.addEventListener("click", () => {
    const open = !sidebar.classList.contains("mobile-open");
    sidebar.classList.toggle("mobile-open", open); overlay.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
  });
  overlay?.addEventListener("click", closeMenu);
  const dialog = document.getElementById("workspace-command");
  const input = document.getElementById("command-input");
  const results = document.getElementById("command-results");
  const links = Array.from(document.querySelectorAll(".workspace-nav a"));
  const render = () => {
    results.replaceChildren();
    const query = input.value.trim().toLocaleLowerCase("uk");
    links.filter(link => link.textContent.toLocaleLowerCase("uk").includes(query)).forEach(link => {
      const item = link.cloneNode(true); item.className = "command-result"; item.removeAttribute("onclick");
      results.append(item);
    });
    if (!results.children.length) { const text = document.createElement("p"); text.textContent = "Сторінок не знайдено."; text.className = "command-hint"; results.append(text); }
  };
  const openCommand = () => { if (!dialog.open) { dialog.showModal(); input.value = ""; render(); input.focus(); } };
  document.getElementById("workspace-search-toggle")?.addEventListener("click", openCommand);
  document.getElementById("command-close")?.addEventListener("click", () => dialog.close());
  input?.addEventListener("input", render);
  input?.addEventListener("keydown", event => {
    if (event.key === "Enter") { const first = results.querySelector("a"); if (first) { event.preventDefault(); first.click(); } }
  });
  dialog?.addEventListener("click", event => { if (event.target === dialog) { const bounds = dialog.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close(); } });
  document.addEventListener("keydown", event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); openCommand(); } if (event.key === "Escape") closeMenu(); });
  const mountPreferences = () => {
    const preferences = document.querySelector(".so-i18n-switcher");
    const header = document.querySelector(".topbar-right");
    if (preferences && header && preferences.parentElement !== header) {
      preferences.classList.remove("so-i18n-floating");
      header.prepend(preferences);
    }
  };
  mountPreferences();
  document.addEventListener("DOMContentLoaded", mountPreferences, {once:true});
  if (typeof bootstrap !== "undefined" && !window.bootstrap) window.bootstrap = bootstrap;
})();
