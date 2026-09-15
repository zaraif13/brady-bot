import {
  adminUnlock,
  listUsers,
  createUser,
  updateUser,
  deleteUser,
  listApis,
  getApi,
  updateApi,
  testOddsApi,
  getMe,
  logout,
  loginPath,
} from "./api.js";

const backdrop = document.getElementById("admin-modal");
const panel = document.getElementById("admin-modal-panel");
const titleEl = document.getElementById("admin-modal-title");
const bodyEl = document.getElementById("admin-modal-body");
const btnSettings = document.getElementById("btn-settings");
const btnClose = document.getElementById("admin-modal-close");

let unlocked = false;
let isSuperadmin = false;
let activeTab = "users";

const EYE_HTML = `
  <svg class="icon-eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
  <svg class="icon-eye-off" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" hidden>
    <path d="M3 3l18 18" />
    <path d="M10.6 10.6a2 2 0 0 0 2.8 2.8" />
    <path d="M9.9 5.1A10.4 10.4 0 0 1 12 5c6.5 0 10 7 10 7a18.5 18.5 0 0 1-2.2 3.1" />
    <path d="M6.1 6.1C3.7 7.8 2 12 2 12s3.5 7 10 7a10.4 10.4 0 0 0 4.2-.9" />
  </svg>
`;

function openModal() {
  backdrop.hidden = false;
  if (unlocked) {
    renderAdminShell();
  } else {
    renderUnlockForm();
  }
}

function closeModal() {
  backdrop.hidden = true;
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function wireShowPassword(btn, input) {
  if (!btn || !input) return;
  btn.addEventListener("click", () => {
    const showing = input.type === "text";
    const next = !showing;
    input.type = next ? "text" : "password";
    btn.setAttribute("aria-pressed", String(next));
    btn.setAttribute("aria-label", next ? "Hide password" : "Show password");
    btn.title = next ? "Hide password" : "Show password";
    const eye = btn.querySelector(".icon-eye");
    const eyeOff = btn.querySelector(".icon-eye-off");
    if (eye) eye.hidden = next;
    if (eyeOff) eyeOff.hidden = !next;
  });
}

function renderUnlockForm() {
  titleEl.textContent = "Admin access";
  panel.classList.remove("modal-wide");
  bodyEl.innerHTML = `
    <form class="admin-form" id="admin-unlock-form">
      <label class="login-label" for="admin-password">Password</label>
      <input class="login-input" type="password" id="admin-password" autocomplete="off" required />
      <p id="admin-error" class="form-error" hidden></p>
      <button type="submit" class="atlas-btn atlas-btn-primary">Unlock</button>
    </form>
  `;
  const form = document.getElementById("admin-unlock-form");
  const errEl = document.getElementById("admin-error");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errEl.hidden = true;
    const password = document.getElementById("admin-password").value;
    try {
      await adminUnlock(password);
      unlocked = true;
      await renderAdminShell();
    } catch (err) {
      errEl.textContent = err.message || "Unlock failed";
      errEl.hidden = false;
    }
  });
  document.getElementById("admin-password").focus();
}

async function refreshSuperadminFlag() {
  try {
    const me = await getMe();
    isSuperadmin = Boolean(me.is_superadmin);
  } catch (_) {
    isSuperadmin = false;
  }
  if (!isSuperadmin && activeTab === "apis") activeTab = "users";
}

async function renderAdminShell() {
  titleEl.textContent = "Admin";
  panel.classList.add("modal-wide");
  bodyEl.innerHTML = `<p class="empty-hint">Loading…</p>`;
  await refreshSuperadminFlag();

  const tabs = isSuperadmin
    ? `
    <div class="admin-tabs" role="tablist">
      <button type="button" class="admin-tab ${activeTab === "users" ? "is-active" : ""}" data-tab="users" role="tab">Users</button>
      <button type="button" class="admin-tab ${activeTab === "apis" ? "is-active" : ""}" data-tab="apis" role="tab">APIs</button>
    </div>`
    : "";

  bodyEl.innerHTML = `
    ${tabs}
    <div id="admin-tab-content"></div>
    <div class="admin-footer">
      <button type="button" class="atlas-btn atlas-btn-secondary" id="admin-logout">Log out</button>
    </div>
  `;

  bodyEl.querySelectorAll(".admin-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTab = btn.getAttribute("data-tab") || "users";
      renderAdminShell();
    });
  });

  document.getElementById("admin-logout").addEventListener("click", async () => {
    try {
      await logout();
    } catch (_) {}
    window.location.replace(loginPath());
  });

  const content = document.getElementById("admin-tab-content");
  if (activeTab === "apis" && isSuperadmin) {
    await renderApisTab(content);
  } else {
    await renderUsersTab(content);
  }
}

async function renderUsersTab(root) {
  root.innerHTML = `<p class="empty-hint">Loading…</p>`;
  let users = [];
  try {
    const data = await listUsers();
    users = data.users || [];
  } catch (err) {
    unlocked = false;
    renderUnlockForm();
    const errEl = document.getElementById("admin-error");
    if (errEl) {
      errEl.textContent = err.message || "Admin session expired";
      errEl.hidden = false;
    }
    return;
  }

  const rows = users.length
    ? users
        .map(
          (u) => `
      <div class="admin-user-row" data-user-id="${escapeHtml(u.id)}">
        <div class="admin-user-email">${escapeHtml(u.username)}</div>
        <div class="admin-user-actions">
          <button type="button" class="atlas-btn atlas-btn-secondary atlas-btn-sm" data-action="edit">Edit</button>
          <button type="button" class="atlas-btn atlas-btn-secondary atlas-btn-sm" data-action="delete">Delete</button>
        </div>
      </div>`
        )
        .join("")
    : `<p class="empty-hint">No users yet. Create one below.</p>`;

  root.innerHTML = `
    <div class="admin-users" id="admin-users-list">${rows}</div>
    <form class="admin-form" id="admin-create-form">
      <div class="admin-create-grid">
        <div class="admin-field">
          <label class="login-label" for="new-user-email">Username</label>
          <input class="login-input" type="email" id="new-user-email" required placeholder="user@example.com" />
        </div>
        <div class="admin-field">
          <label class="login-label" for="new-user-password">Password</label>
          <input class="login-input" type="password" id="new-user-password" required />
          <button
            type="button"
            class="btn-show-password"
            id="show-new-user-password"
            aria-label="Show password"
            aria-pressed="false"
            title="Show password"
          >${EYE_HTML}</button>
        </div>
      </div>
      <div class="admin-create-actions">
        <button type="submit" class="atlas-btn atlas-btn-primary atlas-btn-sm">Add user</button>
      </div>
      <p id="admin-create-error" class="form-error" hidden></p>
    </form>
  `;

  wireShowPassword(
    document.getElementById("show-new-user-password"),
    document.getElementById("new-user-password")
  );

  document.getElementById("admin-create-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errEl = document.getElementById("admin-create-error");
    errEl.hidden = true;
    const username = document.getElementById("new-user-email").value.trim();
    const password = document.getElementById("new-user-password").value;
    try {
      await createUser(username, password);
      await renderAdminShell();
    } catch (err) {
      errEl.textContent = err.message || "Create failed";
      errEl.hidden = false;
    }
  });

  root.querySelectorAll(".admin-user-row").forEach((row) => {
    const id = row.getAttribute("data-user-id");
    const email = row.querySelector(".admin-user-email")?.textContent || "";
    row.querySelector('[data-action="delete"]')?.addEventListener("click", async () => {
      if (!confirm(`Delete user ${email}?`)) return;
      try {
        await deleteUser(id);
        await renderAdminShell();
      } catch (err) {
        alert(err.message || "Delete failed");
      }
    });
    row.querySelector('[data-action="edit"]')?.addEventListener("click", () => {
      if (row.querySelector(".admin-edit-block")) return;
      const edit = document.createElement("div");
      edit.className = "admin-edit-block";
      edit.innerHTML = `
        <label class="login-label">Email</label>
        <input class="login-input" type="email" data-field="email" value="${escapeHtml(email)}" />
        <label class="login-label">New password (leave blank to keep)</label>
        <input class="login-input" type="password" data-field="password" />
        <div class="admin-user-actions">
          <button type="button" class="atlas-btn atlas-btn-primary atlas-btn-sm" data-save>Save</button>
          <button type="button" class="atlas-btn atlas-btn-secondary atlas-btn-sm" data-cancel>Cancel</button>
        </div>
        <p class="form-error" data-edit-error hidden></p>
      `;
      row.appendChild(edit);
      edit.querySelector("[data-cancel]").addEventListener("click", () => edit.remove());
      edit.querySelector("[data-save]").addEventListener("click", async () => {
        const errEl = edit.querySelector("[data-edit-error]");
        errEl.hidden = true;
        const nextEmail = edit.querySelector('[data-field="email"]').value.trim();
        const nextPw = edit.querySelector('[data-field="password"]').value;
        const payload = {};
        if (nextEmail && nextEmail !== email) payload.username = nextEmail;
        if (nextPw) payload.password = nextPw;
        if (!Object.keys(payload).length) {
          edit.remove();
          return;
        }
        try {
          await updateUser(id, payload);
          await renderAdminShell();
        } catch (err) {
          errEl.textContent = err.message || "Update failed";
          errEl.hidden = false;
        }
      });
    });
  });
}

async function renderApisTab(root) {
  root.innerHTML = `<p class="empty-hint">Loading…</p>`;
  let apis = [];
  try {
    const data = await listApis();
    apis = data.apis || [];
  } catch (err) {
    if (err.status === 403) {
      activeTab = "users";
      await renderAdminShell();
      return;
    }
    unlocked = false;
    renderUnlockForm();
    return;
  }

  // Load full keys for inline editing
  const fullById = {};
  await Promise.all(
    apis.map(async (a) => {
      try {
        fullById[a.id] = await getApi(a.id);
      } catch (_) {
        fullById[a.id] = { ...a, key: "" };
      }
    })
  );

  const displayLabel = (a) =>
    a.id === "the_odds_api" ? "Odds API" : a.label || a.id;

  const rows = apis.length
    ? apis
        .map((a) => {
          const full = fullById[a.id] || {};
          return `
      <div class="admin-api-row" data-api-id="${escapeHtml(a.id)}">
        <div class="admin-api-name">${escapeHtml(displayLabel(a))}</div>
        <div class="admin-api-key-wrap">
          <input
            class="login-input admin-api-key-input"
            type="password"
            data-field="key"
            value="${escapeHtml(full.key || "")}"
            autocomplete="off"
            spellcheck="false"
          />
          <button
            type="button"
            class="btn-show-password"
            data-show-key
            aria-label="Show password"
            aria-pressed="false"
            title="Show password"
          >${EYE_HTML}</button>
        </div>
        <div class="admin-api-actions">
          <button type="button" class="atlas-btn atlas-btn-primary atlas-btn-sm" data-action="save">Save</button>
          ${
            a.id === "the_odds_api"
              ? '<button type="button" class="atlas-btn atlas-btn-secondary atlas-btn-sm" data-action="test">Test</button>'
              : ""
          }
        </div>
        <p class="admin-api-status" data-status hidden></p>
      </div>`;
        })
        .join("")
    : `<p class="empty-hint">No APIs configured yet.</p>`;

  root.innerHTML = `<div class="admin-apis">${rows}</div>`;

  root.querySelectorAll(".admin-api-row").forEach((row) => {
    const id = row.getAttribute("data-api-id");
    const statusEl = row.querySelector("[data-status]");
    const keyInput = row.querySelector('[data-field="key"]');
    wireShowPassword(row.querySelector("[data-show-key]"), keyInput);

    row.querySelector('[data-action="save"]')?.addEventListener("click", async () => {
      statusEl.hidden = false;
      statusEl.textContent = "Saving…";
      statusEl.className = "admin-api-status";
      try {
        await updateApi(id, { key: keyInput.value });
        statusEl.textContent = "Saved";
        statusEl.classList.add("is-ok");
      } catch (err) {
        statusEl.textContent = err.message || "Save failed";
        statusEl.classList.add("is-bad");
      }
    });

    row.querySelector('[data-action="test"]')?.addEventListener("click", async () => {
      statusEl.hidden = false;
      statusEl.textContent = "Testing…";
      statusEl.className = "admin-api-status";
      try {
        // Persist current field first so test uses what's on screen
        await updateApi(id, { key: keyInput.value });
        const result = await testOddsApi();
        statusEl.textContent = result.message || (result.ok ? "OK" : "Failed");
        statusEl.classList.toggle("is-ok", Boolean(result.ok));
        statusEl.classList.toggle("is-bad", !result.ok);
      } catch (err) {
        statusEl.textContent = err.message || "Test failed";
        statusEl.classList.add("is-bad");
      }
    });
  });
}

btnSettings?.addEventListener("click", openModal);
btnClose?.addEventListener("click", closeModal);
backdrop?.addEventListener("click", (e) => {
  if (e.target === backdrop) closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && backdrop && !backdrop.hidden) closeModal();
});
