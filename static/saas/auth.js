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
    sms: "Код SMS неправильний, сплив або належить іншому номеру. Спробуйте ще раз.",
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
    const updateIndustry = () => {
      document.getElementById("retail-category").hidden = type.value !== "retail";
      const standard = type.selectedOptions[0]?.dataset.plan === "plan1";
      form.querySelectorAll("[data-industry]").forEach(summary => {
        summary.hidden = summary.dataset.industry !== type.value;
      });
      form.querySelector("[data-standard-plans]").hidden = !standard;
      form.querySelector("[data-standard-terms]").hidden = !standard;
      form.querySelector("[data-industry-terms]").hidden = standard;
      const unavailable = form.querySelector("[data-standard-unavailable]");
      if (unavailable) {
        unavailable.hidden = !standard;
        form.querySelector('button[type="submit"]').disabled = standard;
      }
    };
    updateIndustry();
    type.addEventListener("change", updateIndustry);
    const sendCode = form.querySelector("[data-send-code]");
    if (sendCode) {
      const phone = form.querySelector("#register-phone");
      const code = form.querySelector("#register-sms-code");
      const message = form.querySelector("[data-sms-message]");
      sendCode.addEventListener("click", async () => {
        if (!phone.reportValidity()) return;
        sendCode.disabled = true;
        code.value = "";
        message.hidden = false;
        message.textContent = "Надсилаємо код…";
        const data = new URLSearchParams({
          phone: phone.value,
          csrf_token: form.querySelector('input[name="csrf_token"]').value,
        });
        try {
          const result = await fetch("/register/phone", { method: "POST", body: data, headers: { Accept: "application/json" },
            signal: AbortSignal.timeout(15000) });
          const status = await result.json();
          message.textContent = status.message || "Не вдалося надіслати код. Спробуйте пізніше.";
          if (result.ok) code.focus();
        } catch {
          message.textContent = "Не вдалося надіслати код. Спробуйте пізніше.";
        } finally {
          sendCode.disabled = false;
        }
      });
    }
    document.getElementById("continue-registration").addEventListener("click", () => {
      for (const field of steps[0].querySelectorAll("input,select")) {
        if (!field.reportValidity()) return;
      }
      showStep(2);
      steps[1].querySelector('input[type="radio"]:checked')?.focus();
    });
    document.getElementById("back-registration").addEventListener("click", () => { showStep(1); });
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
    if (form.hasAttribute("data-creem-checkout")) return;
    form.addEventListener("submit", () => {
      const button = form.querySelector('button[type="submit"]');
      if (button) { button.disabled = true; button.setAttribute("aria-busy", "true"); const label = button.querySelector("span"); if (label) { button.dataset.idleLabel = label.textContent; label.textContent = "Зачекайте…"; } }
    });
  });
  document.querySelectorAll("[data-creem-checkout]").forEach(form => {
    const button = form.querySelector('button[type="submit"]');
    const feedback = form.querySelector("[data-checkout-feedback]");
    const checkoutLink = form.querySelector("[data-checkout-link]");
    const submitCheckout = async (verifyOnly = false) => {
      if (button.disabled) return;
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      feedback.textContent = verifyOnly ? "Перевіряємо платіж у Creem…" : "Готуємо касу Creem…";
      feedback.hidden = false;
      checkoutLink.hidden = true;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 30000);
      try {
        const payload = new FormData(form);
        if (verifyOnly) payload.set("verify_only", "true");
        const response = await fetch(form.action, {
          method: "POST",
          headers: { Accept: "application/json" },
          body: payload,
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Checkout request failed");
        const { location } = await response.json();
        if (typeof location !== "string" || !location) throw new Error("Checkout link missing");
        const url = new URL(location, window.location.origin);
        if (url.origin === window.location.origin) {
          window.location.assign(url.href);
          return;
        }
        if (url.protocol !== "https:" || !["creem.io", "www.creem.io", "checkout.creem.io"].includes(url.host)) {
          throw new Error("Unexpected checkout host");
        }
        checkoutLink.href = url.href;
        checkoutLink.hidden = false;
        feedback.textContent = "Якщо каса не відкриється автоматично, скористайтеся посиланням нижче.";
        window.location.assign(url.href);
      } catch {
        feedback.textContent = "Не вдалося відкрити касу Creem. Спробуйте ще раз.";
      } finally {
        clearTimeout(timeout);
        button.disabled = false;
        button.removeAttribute("aria-busy");
      }
    };
    form.addEventListener("submit", event => {
      event.preventDefault();
      void submitCheckout();
    });
    if (new URLSearchParams(location.search).get("checkout_return") === "1") {
      void submitCheckout(true);
    }
  });
  window.addEventListener("pageshow", () => {
    document.querySelectorAll('button[aria-busy="true"]').forEach(button => {
      button.disabled = false; button.removeAttribute("aria-busy");
      if (button.dataset.idleLabel) button.querySelector("span").textContent = button.dataset.idleLabel;
    });
  });
})();
