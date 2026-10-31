const form = document.querySelector("[data-auth-form]");

document.querySelectorAll("[data-password-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.passwordToggle);
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    button.setAttribute("aria-pressed", String(reveal));
    button.textContent = reveal ? "Hide" : "Show";
  });
});

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector('button[type="submit"]');
  const message = form.querySelector("[data-message]");
  const originalLabel = button.textContent;
  let completed = false;
  button.disabled = true;
  button.textContent = "Please wait…";
  message.textContent = "";
  message.className = "form-message";

  try {
    const response = await fetch(form.action, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Unable to complete your request.");

    if (form.dataset.authForm === "login" || form.dataset.authForm === "signup") {
      const requestedPath = new URLSearchParams(location.search).get("next");
      const nextPath = requestedPath?.startsWith("/") && !requestedPath.startsWith("//")
        ? requestedPath
        : "/";
      location.assign(form.dataset.authForm === "login" ? nextPath : "/");
      return;
    }

    message.textContent = result.message;
    message.classList.add("success");
    if (form.dataset.authForm === "reset") {
      form.querySelectorAll("input, button[type=submit]").forEach((element) => {
        element.disabled = true;
      });
      button.textContent = "Password reset";
      completed = true;
      return;
    }
    form.reset();
  } catch (error) {
    message.textContent = error.message;
    message.classList.add("error");
  } finally {
    if (!completed) {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }
});

const resetToken = document.getElementById("resetToken");
if (resetToken) resetToken.value = new URLSearchParams(location.search).get("token") || "";
