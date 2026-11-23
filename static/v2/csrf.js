(() => {
  "use strict";
  const token = document.querySelector('meta[name="csrf-token"]')?.content;
  if (!token) return;
  const attach = form => {
    if ((form.method || "get").toLowerCase() !== "post") return;
    let field = form.querySelector('input[name="csrf_token"]');
    if (!field) { field = document.createElement("input"); field.type = "hidden"; field.name = "csrf_token"; form.append(field); }
    field.value = token;
  };
  document.querySelectorAll("form").forEach(attach);
  document.addEventListener("submit", event => { if (event.target instanceof HTMLFormElement) attach(event.target); }, true);
  const original = window.fetch;
  window.fetch = (input, options = {}) => {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    const method = (options.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    if (url.origin === location.origin && !["GET", "HEAD", "OPTIONS"].includes(method)) {
      const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
      headers.set("X-CSRF-Token", token);
      options = {...options, headers};
    }
    return original(input, options);
  };
})();
