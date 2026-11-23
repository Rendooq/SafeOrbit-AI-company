/* Small progressive enhancement: native forms still work without JavaScript. */
(() => {
  "use strict";
  const errors = {
    invalid: "Телефон або пароль не збігаються. Перевірте дані та спробуйте ще раз.",
    inactive: "Ваш простір ще не активовано або його доступ призупинено. Зверніться до адміністратора.",
    exists: "Акаунт із цим телефоном уже існує. Увійдіть у свій простір.",
    fields: "Перевірте назву бізнесу, телефон та пароль (щонайменше 8 символів).",
    file: "Додайте PDF, JPG або PNG розміром до 5 МБ.",
    terms: "Потрібно погодитися з умовами підключення.",
    rate: "Забагато спроб. Зачекайте хвилину й повторіть.",
    plan: "Цей тариф зараз недоступний. Оберіть інший або зверніться до адміністратора.",
  };
  const alert = document.getElementById("auth-error");
  const code = new URLSearchParams(location.search).get("error");
  if (alert && errors[code]) { alert.textContent = errors[code]; alert.hidden = false; }

  document.querySelectorAll("[data-password-target]").forEach(button => {
    button.addEventListener("click", () => {
      const field = document.getElementById(button.dataset.passwordTarget);
      const visible = field.type === "password";
      field.type = visible ? "text" : "password";
      button.setAttribute("aria-pressed", String(visible));
      button.setAttribute("aria-label", visible ? "Сховати пароль" : "Показати пароль");
    });
  });
  const form = document.getElementById("register-form");
  if (form) {
    const steps = Array.from(form.querySelectorAll("[data-step]"));
    let step = 1;
    const showStep = value => {
      step = value;
      steps.forEach(section => { section.hidden = Number(section.dataset.step) !== value; });
      document.querySelectorAll("[data-step-label]").forEach(label => {
        label.classList.toggle("active", Number(label.dataset.stepLabel) === value);
      });
    };
    showStep(1);
    const type = document.getElementById("business-type");
    type.addEventListener("change", () => { document.getElementById("retail-category").hidden = type.value !== "retail"; });
    document.getElementById("continue-registration").addEventListener("click", () => {
      for (const field of steps[0].querySelectorAll("input,select")) {
        if (!field.reportValidity()) return;
      }
      showStep(2);
      steps[1].querySelector('input[type="radio"]:checked')?.focus();
    });
    document.getElementById("back-registration").addEventListener("click", () => { showStep(1); });
    const country = document.getElementById("payment-country");
    const creem = country.querySelector('option[value="creem"]');
    const receipt = document.getElementById("payment-file");
    const promo = document.getElementById("promo-code");
    const updatePayment = () => {
      if (creem) {
        const plan = form.querySelector('input[name="plan_type"]:checked')?.value;
        creem.disabled = !creem.dataset.plans.split(" ").includes(plan);
        if (creem.selected && creem.disabled) country.value = "ua";
        const online = country.value === "creem";
        document.getElementById("creem-payment-note").hidden = !online;
        form.querySelector(".payment-details").hidden = online;
        receipt.closest(".field").hidden = online;
        receipt.disabled = online;
        receipt.required = !online;
        promo.closest(".field").hidden = online;
        promo.disabled = online;
      }
      document.querySelectorAll("[data-payment-profile]").forEach(profile => {
        profile.hidden = profile.dataset.paymentProfile !== country.value;
      });
    };
    country.addEventListener("change", updatePayment);
    form.querySelectorAll('input[name="plan_type"]').forEach(input => input.addEventListener("change", updatePayment));
    updatePayment();
    form.querySelectorAll('input[type="file"]').forEach(upload => {
      upload.addEventListener("change", () => {
        upload.setCustomValidity(upload.files[0]?.size > 5 * 1024 * 1024 ? errors.file : "");
        upload.reportValidity();
      });
    });
    form.addEventListener("invalid", event => {
      if (event.target.closest("[data-step]")?.dataset.step === "1") showStep(1);
    }, true);
  }
  document.querySelectorAll("form").forEach(form => {
    form.addEventListener("submit", () => {
      const button = form.querySelector('button[type="submit"]');
      if (button) { button.disabled = true; button.setAttribute("aria-busy", "true"); const label = button.querySelector("span"); if (label) { button.dataset.idleLabel = label.textContent; label.textContent = "Зачекайте…"; } }
    });
  });
  window.addEventListener("pageshow", () => {
    document.querySelectorAll('button[aria-busy="true"]').forEach(button => {
      button.disabled = false; button.removeAttribute("aria-busy");
      if (button.dataset.idleLabel) button.querySelector("span").textContent = button.dataset.idleLabel;
    });
  });
})();
