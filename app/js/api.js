/** API client — base path supports /brady-bot subdirectory hosting. */
const BASE_PATH =
  typeof window !== "undefined" && window.location.pathname.includes("/brady-bot")
    ? "/brady-bot"
    : (typeof window !== "undefined" && window.__BRADY_BASE__) || "";

export function appHomePath() {
  return BASE_PATH ? `${BASE_PATH}/` : "/";
}

/** nginx serves section pages as static files; local uvicorn also serves the clean route. */
export function sectionPath(section) {
  if (!BASE_PATH) return section.route;
  return section.route === "/" ? `${BASE_PATH}/` : `${BASE_PATH}/${section.page}`;
}

export function loginPath() {
  // nginx aliases login.html; local uvicorn also serves /login
  return BASE_PATH ? `${BASE_PATH}/login.html` : "/login";
}

async function api(path, options = {}) {
  const url = `${BASE_PATH}${path}`;
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) {}
    const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

export function searchPlayers(q, slot) {
  const params = new URLSearchParams({ q, slot });
  return api(`/api/players/search?${params}`);
}

export function getMetaWeek() {
  return api("/api/meta/week");
}

export function getRoster() {
  return api("/api/roster");
}

export function saveRoster(payload) {
  return api("/api/roster", { method: "PUT", body: JSON.stringify(payload) });
}

export function pickLineup(payload) {
  return api("/api/lineup/pick", { method: "POST", body: JSON.stringify(payload) });
}

export function getMe() {
  return api("/api/auth/me");
}

export function login(username, password) {
  return api("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function logout() {
  return api("/api/auth/logout", { method: "POST", body: "{}" });
}

export function adminUnlock(password) {
  return api("/api/admin/unlock", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

export function listUsers() {
  return api("/api/admin/users");
}

export function createUser(username, password) {
  return api("/api/admin/users", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function updateUser(id, payload) {
  return api(`/api/admin/users/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteUser(id) {
  return api(`/api/admin/users/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function listApis() {
  return api("/api/admin/apis");
}

export function getApi(id) {
  return api(`/api/admin/apis/${encodeURIComponent(id)}`);
}

export function createApi(id, label, key) {
  return api("/api/admin/apis", {
    method: "POST",
    body: JSON.stringify({ id, label, key }),
  });
}

export function updateApi(id, payload) {
  return api(`/api/admin/apis/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteApi(id) {
  return api(`/api/admin/apis/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function testOddsApi() {
  return api("/api/admin/apis/the_odds_api/test", {
    method: "POST",
    body: "{}",
  });
}

export function listTrueDepthTeams() {
  return api("/api/true-depth");
}

export function getTrueDepthTeam(team) {
  return api(`/api/true-depth/${encodeURIComponent(team)}`);
}

export function getOpportunityShareMeta() {
  return api("/api/opportunity-share");
}

export function getOpportunityShareTeam(team, view = "all") {
  const q = new URLSearchParams({ view: String(view) });
  return api(
    `/api/opportunity-share/${encodeURIComponent(team)}?${q.toString()}`
  );
}
