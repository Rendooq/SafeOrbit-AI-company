/* Runs before styles paint. Storage is optional; a blocked store never breaks UI. */
(() => {
  let theme = "light";
  try {
    const saved = localStorage.getItem("safeorbit-theme");
    if (saved === "light" || saved === "dark") theme = saved;
  } catch (_) {}
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.bsTheme = theme;
})();
