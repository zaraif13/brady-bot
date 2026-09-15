import { getMe, loginPath, listTrueDepthTeams, getTrueDepthTeam } from "../api.js";
import { renderNav } from "../nav.js";
import {
  renderTrueDepthChart,
  renderOtherStarterInjuries,
} from "./true-depth-render.js";

renderNav();

const DEFAULT_TEAM = "BUF";

const teamSelect = document.getElementById("tdc-team");
const switchBtn = document.getElementById("tdc-switch");
const legend = document.getElementById("tdc-legend");
const statusEl = document.getElementById("tdc-status");
const chartRoot = document.getElementById("tdc-chart");
const modeLeft = document.getElementById("tdc-mode-left");
const modeRight = document.getElementById("tdc-mode-right");

/** @type {boolean} preserved across team changes */
let trueMode = false;
/** @type {object|null} */
let currentPayload = null;

function setStatus(msg) {
  statusEl.hidden = !msg;
  statusEl.textContent = msg || "";
}

function clearInjuries() {
  renderOtherStarterInjuries({ OL: "—", DL: "—", LBs: "—", DBs: "—" });
}

function syncToggleUi() {
  switchBtn.classList.toggle("is-on", trueMode);
  switchBtn.setAttribute("aria-checked", String(trueMode));
  legend.hidden = !trueMode;
  modeLeft.classList.toggle("is-active", !trueMode);
  modeRight.classList.toggle("is-active", trueMode);
}

function render() {
  syncToggleUi();
  if (!currentPayload) {
    chartRoot.innerHTML = "";
    clearInjuries();
    return;
  }
  chartRoot.innerHTML = renderTrueDepthChart(currentPayload, trueMode);
  renderOtherStarterInjuries(currentPayload.other_starter_injuries);
  setStatus(
    trueMode && currentPayload.has_usage_data === false
      ? "No regular-season usage recorded yet — True order mirrors the published chart."
      : ""
  );
}

function populateTeamSelect(teams) {
  teamSelect.innerHTML = teams
    .map((t) => `<option value="${t.code}">${t.code} — ${t.name}</option>`)
    .join("");
  const codes = teams.map((t) => t.code);
  teamSelect.value = codes.includes(DEFAULT_TEAM) ? DEFAULT_TEAM : codes[0] || "";
}

async function loadTeam(team) {
  if (!team) return;
  setStatus("");
  currentPayload = null;
  chartRoot.innerHTML = '<p class="empty-hint">Loading…</p>';
  clearInjuries();

  try {
    currentPayload = await getTrueDepthTeam(team);
    render();
  } catch (e) {
    currentPayload = null;
    chartRoot.innerHTML = "";
    clearInjuries();
    setStatus(
      e.status === 404
        ? `No published depth chart available for ${team} yet.`
        : e.message || String(e)
    );
  }
}

switchBtn.addEventListener("click", () => {
  trueMode = !trueMode;
  render();
});

teamSelect.addEventListener("change", () => {
  loadTeam(teamSelect.value);
});

async function init() {
  try {
    await getMe();
  } catch (_) {
    window.location.replace(loginPath());
    return;
  }

  syncToggleUi();

  let teams = [];
  try {
    const meta = await listTrueDepthTeams();
    teams = meta.teams || [];
  } catch (e) {
    setStatus(e.message || String(e));
    return;
  }

  populateTeamSelect(teams);
  await loadTeam(teamSelect.value);
}

init();
