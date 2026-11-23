(() => {
  "use strict";
  const root = document.documentElement;
  const syncButtons = () => {
    const dark = root.dataset.theme === "dark";
    const t = value => window.SafeOrbitI18N?.translate(value) || value;
    document.querySelectorAll("[data-theme-toggle]").forEach(button => {
      button.setAttribute("aria-pressed", String(dark));
      button.setAttribute("aria-label", t(dark ? "Увімкнути світлу тему" : "Увімкнути чорну тему"));
      button.title = t(dark ? "Світла тема" : "Чорна тема");
      const text = button.querySelector("[data-theme-label]");
      if (text) text.textContent = t(dark ? "Світла тема" : "Чорна тема");
    });
  };
  const apply = (theme, save = true) => {
    root.dataset.theme = theme === "dark" ? "dark" : "light";
    root.dataset.bsTheme = root.dataset.theme;
    if (save) {
      try { localStorage.setItem("safeorbit-theme", root.dataset.theme); } catch (_) {}
    }
    syncButtons();
    window.dispatchEvent(new CustomEvent("safeorbit:themechange", {detail: root.dataset.theme}));
    const colors = getComputedStyle(root);
    if (window.Chart) {
      Chart.defaults.color = colors.getPropertyValue("--ui-muted").trim();
      Object.values(Chart.instances || {}).forEach(chart => {
        Object.values(chart.options.scales || {}).forEach(scale => {
          if (scale.ticks) scale.ticks.color = colors.getPropertyValue("--ui-muted").trim();
          if (scale.grid && scale.grid.display !== false) scale.grid.color = colors.getPropertyValue("--ui-border").trim();
        });
        if (chart.options.plugins?.legend?.labels) chart.options.plugins.legend.labels.color = colors.getPropertyValue("--ui-text").trim();
        chart.update("none");
      });
    }
  };
  document.querySelectorAll("[data-theme-toggle]").forEach(button => {
    button.addEventListener("click", () => apply(root.dataset.theme === "dark" ? "light" : "dark"));
  });
  window.addEventListener("storage", event => {
    if (event.key === "safeorbit-theme") apply(event.newValue, false);
  });
  window.addEventListener("safeorbit:language-changed", syncButtons);
  syncButtons();
})();
