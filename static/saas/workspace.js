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
  sidebar?.querySelector(".workspace-nav")?.addEventListener("click", event => {
    if (event.target.closest("a")) closeMenu();
  });
  if (document.body.dataset.active === "dash") {
    const currentLinks = [document.getElementById("menu-dash"), document.getElementById("menu-agenda")];
    const syncLocation = () => {
      const inAgenda = location.hash === "#day-agenda";
      currentLinks.forEach((link, index) => {
        if (!link) return;
        const selected = index === (inAgenda ? 1 : 0);
        link.classList.toggle("active", selected);
        if (selected) link.setAttribute("aria-current", inAgenda ? "location" : "page");
        else link.removeAttribute("aria-current");
      });
    };
    syncLocation();
    window.addEventListener("hashchange", syncLocation);
  }
  const dialog = document.getElementById("workspace-command");
  const input = document.getElementById("command-input");
  const results = document.getElementById("command-results");
  const links = Array.from(document.querySelectorAll(".workspace-nav a"));
  const render = () => {
    results.replaceChildren();
    const query = input.value.trim().toLocaleLowerCase("uk");
    links.filter(link => link.textContent.toLocaleLowerCase("uk").includes(query)).forEach(link => {
      const item = link.cloneNode(true); item.className = "command-result"; item.removeAttribute("onclick");
      item.removeAttribute("id");
      item.removeAttribute("aria-current");
      results.append(item);
    });
    if (!results.children.length) { const text = document.createElement("p"); text.textContent = "Сторінок не знайдено."; text.className = "command-hint"; results.append(text); }
  };
  const openCommand = () => { if (!dialog.open) { dialog.showModal(); input.value = ""; render(); input.focus(); } };
  document.getElementById("workspace-search-toggle")?.addEventListener("click", openCommand);
  document.getElementById("command-close")?.addEventListener("click", () => dialog.close());
  results?.addEventListener("click", event => {
    if (event.target.closest("a")) dialog.close();
  });
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
