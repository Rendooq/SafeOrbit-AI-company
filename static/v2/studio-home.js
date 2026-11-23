(() => {
  "use strict";
  const stage = document.querySelector(".workspace-stage");
  if (!stage) return;

  const switcher = stage.querySelector(".view-switch");
  const tabs = Array.from(switcher.querySelectorAll("[data-tab]"));
  const panels = Array.from(stage.querySelectorAll("[data-panel]"));
  const profiles = Array.from(stage.querySelectorAll("[data-profile]"));
  let client = profiles[0].dataset.profile;

  function showView(name) {
    for (const tab of tabs) {
      const active = tab.dataset.tab === name;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    }
    for (const panel of panels) panel.hidden = panel.dataset.panel !== name;
    for (const profile of profiles) profile.hidden = profile.dataset.profile !== client;
    return tabs.find(tab => tab.dataset.tab === name);
  }

  function showLocation() {
    const target = document.getElementById(location.hash.slice(1));
    if (target?.dataset.profile) {
      client = target.dataset.profile;
      showView("client");
    } else {
      showView(target?.dataset.panel || "schedule");
    }
  }

  switcher.setAttribute("role", "tablist");
  for (const tab of tabs) {
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", "panel-" + tab.dataset.tab);
    tab.addEventListener("click", event => {
      event.preventDefault();
      showView(tab.dataset.tab);
    });
  }
  for (const panel of panels) {
    panel.setAttribute("role", "tabpanel");
    panel.tabIndex = 0;
  }
  switcher.addEventListener("keydown", event => {
    const index = tabs.indexOf(event.target);
    if (index < 0) return;
    let next;
    switch (event.key) {
      case "ArrowRight": next = (index + 1) % tabs.length; break;
      case "ArrowLeft": next = (index + tabs.length - 1) % tabs.length; break;
      case "Home": next = 0; break;
      case "End": next = tabs.length - 1; break;
      default: return;
    }
    event.preventDefault();
    showView(tabs[next].dataset.tab).focus();
  });

  for (const link of document.querySelectorAll("[data-client], [data-preview-link]")) {
    link.addEventListener("click", event => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      if (link.dataset.client) client = link.dataset.client;
      const selected = showView(link.dataset.previewLink || "client");
      selected.focus({preventScroll: true});
      if (!stage.contains(link)) stage.scrollIntoView({block: "center"});
    });
  }
  showLocation();
  window.addEventListener("hashchange", showLocation);

  const menu = document.querySelector(".mobile-menu");
  document.addEventListener("click", event => {
    if (menu.open && (!menu.contains(event.target) || event.target.closest("a"))) menu.open = false;
  });
  menu.addEventListener("keydown", event => {
    if (event.key === "Escape" && menu.open) {
      menu.open = false;
      menu.querySelector("summary").focus();
    }
  });
})();
