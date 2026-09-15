import {
  getMe,
  loginPath,
  getOpportunityShareMeta,
  getOpportunityShareTeam,
} from "../api.js";
import { renderNav } from "../nav.js";
import { renderOpportunityShareTable } from "./opportunity-share-render.js";

renderNav();

const DEFAULT_TEAM = "BUF";
const DEFAULT_VIEW = "all";

const teamSelect = document.getElementById("opp-team");
const viewSelect = document.getElementById("opp-view");
const statusEl = document.getElementById("opp-status");
const tableRoot = document.getElementById("opp-table-root");
const allBanner = document.getElementById("opp-all-banner");

/** @type {object|null} */
let currentPayload = null;

function setStatus(msg) {
  statusEl.hidden = !msg;
  statusEl.textContent = msg || "";
}

function syncBanner() {
  allBanner.hidden = viewSelect.value !== "all";
}

function populateTeamSelect(teams) {
  teamSelect.innerHTML = teams
    .map((t) => `<option value="${t.code}">${t.code} — ${t.name}</option>`)
    .join("");
  const codes = teams.map((t) => t.code);
  teamSelect.value = codes.includes(DEFAULT_TEAM) ? DEFAULT_TEAM : codes[0] || "";
}

function populateViewSelect(completedWeeks) {
  const weeks = Array.isArray(completedWeeks) ? completedWeeks : [];
  const options = [
    `<option value="all">All</option>`,
    ...weeks.map((w) => `<option value="${w}">Week ${w}</option>`),
  ];
  viewSelect.innerHTML = options.join("");
  viewSelect.value = DEFAULT_VIEW;
}

function render() {
  syncBanner();
  if (!currentPayload) {
    tableRoot.innerHTML = "";
    return;
  }
  tableRoot.innerHTML = renderOpportunityShareTable(currentPayload);
}

async function loadBoard() {
  const team = teamSelect.value;
  const view = viewSelect.value || DEFAULT_VIEW;
  if (!team) return;

  setStatus("");
  currentPayload = null;
  tableRoot.innerHTML = '<p class="empty-hint">Loading…</p>';
  syncBanner();

  try {
    currentPayload = await getOpportunityShareTeam(team, view);
    render();
  } catch (e) {
    currentPayload = null;
    tableRoot.innerHTML = "";
    const label = view === "all" ? "season to date" : `week ${view}`;
    setStatus(
      e.status === 404
        ? `No opportunity share data for ${team} (${label}) yet.`
        : e.message || String(e)
    );
  }
}

teamSelect.addEventListener("change", () => {
  loadBoard();
});

viewSelect.addEventListener("change", () => {
  loadBoard();
});

async function init() {
  try {
    await getMe();
  } catch (_) {
    window.location.replace(loginPath());
    return;
  }

  let meta;
  try {
    meta = await getOpportunityShareMeta();
  } catch (e) {
    setStatus(e.message || String(e));
    return;
  }

  populateTeamSelect(meta.teams || []);
  populateViewSelect(meta.completed_weeks || []);
  await loadBoard();
}

init();
