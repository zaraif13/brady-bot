import { login, getMe, appHomePath } from "./api.js";

const form = document.getElementById("login-form");
const errEl = document.getElementById("login-error");
const submitBtn = document.getElementById("login-submit");

async function redirectIfAuthed() {
  try {
    await getMe();
    window.location.replace(appHomePath());
  } catch (_) {
    /* stay on login */
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errEl.hidden = true;
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  submitBtn.disabled = true;
  try {
    await login(username, password);
    window.location.replace(appHomePath());
  } catch (err) {
    errEl.textContent = err.message || "Login failed";
    errEl.hidden = false;
  } finally {
    submitBtn.disabled = false;
  }
});

redirectIfAuthed();
