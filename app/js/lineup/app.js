import { getMetaWeek, getRoster, saveRoster, pickLineup, getMe, loginPath } from "../api.js";
import { createRosterController } from "./roster.js";
import { renderEmptyLineupCard, renderPlayerCard } from "./cards.js";
import { slotLabel } from "./slots.js";
import { renderNav } from "../nav.js";

renderNav();

const rosterRoot = document.getElementById("roster-slots");
const lineupResult = document.getElementById("lineup-result");
const lineupTitle = document.getElementById("lineup-title");
const lineupWarnings = document.getElementById("lineup-warnings");
const rosterError = document.getElementById("roster-error");
const btnPick = document.getElementById("btn-pick");

let week = 1;

const roster = createRosterController(rosterRoot);

document.getElementById("btn-add-bn").addEventListener("click", () => roster.addBn());
document.getElementById("btn-add-ir").addEventListener("click", () => roster.addIr());
document.getElementById("btn-reset-roster").addEventListener("click", async () => {
  roster.reset();
  rosterError.hidden = true;
  lineupResult.innerHTML =
    '<p class="empty-hint">Fill your roster on the left, then click Pick Lineup.</p>';
  lineupWarnings.hidden = true;
  lineupWarnings.innerHTML = "";
  try {
    await saveRoster({ week, ...roster.getState() });
  } catch (e) {
    rosterError.textContent = e.message || String(e);
    rosterError.hidden = false;
  }
});

btnPick.addEventListener("click", async () => {
  rosterError.hidden = true;
  const players = roster.getPlayers();
  if (!players.length) {
    rosterError.textContent = "Add at least one player before picking a lineup.";
    rosterError.hidden = false;
    return;
  }
  btnPick.disabled = true;
  btnPick.textContent = "Picking…";
  try {
    const payload = {
      week,
      ...roster.getState(),
    };
    await saveRoster(payload);
    const result = await pickLineup(payload);
    week = result.week;
    lineupTitle.textContent = `Gameweek ${result.week} Lineup`;
    renderLineup(result);
    if (result.opponents) roster.setOpponents(result.opponents);
    if (result.injuries_by_player) roster.setInjuries(result.injuries_by_player);
  } catch (e) {
    rosterError.textContent = e.message || String(e);
    rosterError.hidden = false;
  } finally {
    btnPick.disabled = false;
    btnPick.textContent = "Pick Lineup";
  }
});

lineupResult.addEventListener("click", (e) => {
  const btn = e.target.closest(".card-details-toggle");
  if (!btn || !lineupResult.contains(btn)) return;
  e.preventDefault();
  const wrap = btn.closest(".lineup-card-wrap");
  if (!wrap) return;
  const panel = wrap.querySelector(".card-details-panel");
  const chevron = btn.querySelector(".chevron");
  if (!panel) return;
  const open = btn.getAttribute("aria-expanded") === "true";
  const next = !open;
  btn.setAttribute("aria-expanded", String(next));
  panel.hidden = !next;
  if (chevron) chevron.classList.toggle("is-open", next);
});

function appendLineupCard(row, html) {
  const wrap = document.createElement("div");
  wrap.innerHTML = html.trim();
  row.appendChild(wrap.firstElementChild);
}

function detailsOpts(scored, fallbackExplanation) {
  return {
    details: true,
    explanation: scored.explanation || fallbackExplanation,
    start_score: scored.start_score,
    factors: scored.factors || [],
    gate_result: scored.gate_result,
    gate_reason: scored.gate_reason,
    weighted_sum: scored.weighted_sum,
    bonus: scored.bonus,
    flags: scored.flags || [],
    prior_label: scored.prior_label || null,
    prior_start_score: scored.prior_start_score,
    prior_weighted_sum: scored.prior_weighted_sum,
    prior_bonus: scored.prior_bonus || 0,
    prior_flags: scored.prior_flags || [],
    prior_factors: scored.prior_factors || [],
  };
}

function renderLineup(result) {
  lineupResult.innerHTML = "";
  // Display order: positional slots first, FLEX last among starters
  const order = ["QB", "RB1", "RB2", "WR1", "WR2", "TE", "DEF", "K", "FLEX"];
  for (const slot of order) {
    const scored = result.starters?.[slot];
    const row = document.createElement("div");
    row.className = "lineup-slot";
    const label = document.createElement("div");
    label.className = "slot-label";
    label.textContent = slotLabel(slot);
    row.appendChild(label);
    if (!scored) {
      appendLineupCard(row, renderEmptyLineupCard("No eligible player for this slot.", `empty-${slot}`));
    } else {
      const p = {
        player_id: scored.player.player_id,
        name: scored.player.name,
        position: scored.player.position === "DEF" ? "D/ST" : scored.player.position,
        team: scored.player.team,
        headshot: scored.headshot,
        opponent: scored.opponent,
        injury_status: scored.injury_label || scored.injury_status,
      };
      appendLineupCard(row, renderPlayerCard(p, "is-starter", detailsOpts(scored, "Started in this slot.")));
    }
    lineupResult.appendChild(row);
  }

  for (const scored of result.bench || []) {
    const row = document.createElement("div");
    row.className = "lineup-slot";
    const label = document.createElement("div");
    label.className = "slot-label";
    label.textContent = "BN";
    row.appendChild(label);
    const p = {
      player_id: scored.player.player_id,
      name: scored.player.name,
      position: scored.player.position === "DEF" ? "D/ST" : scored.player.position,
      team: scored.player.team,
      headshot: scored.headshot,
      opponent: scored.opponent,
      injury_status: scored.injury_label || scored.injury_status,
    };
    appendLineupCard(row, renderPlayerCard(p, "is-bench", detailsOpts(scored, "Benched this week.")));
    lineupResult.appendChild(row);
  }

  for (const scored of result.ir || []) {
    const row = document.createElement("div");
    row.className = "lineup-slot";
    const label = document.createElement("div");
    label.className = "slot-label";
    label.textContent = "IR";
    row.appendChild(label);
    const p = {
      player_id: scored.player.player_id,
      name: scored.player.name,
      position: scored.player.position === "DEF" ? "D/ST" : scored.player.position,
      team: scored.player.team,
      headshot: scored.headshot,
      opponent: scored.opponent,
      injury_status: scored.injury_label || scored.injury_status,
    };
    appendLineupCard(
      row,
      renderPlayerCard(p, "is-ir", detailsOpts(scored, "On IR slot (excluded from start/bench pool)."))
    );
    lineupResult.appendChild(row);
  }

  if (result.warnings?.length) {
    lineupWarnings.hidden = false;
    lineupWarnings.innerHTML =
      "<ul>" + result.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("") + "</ul>";
  } else {
    lineupWarnings.hidden = true;
    lineupWarnings.innerHTML = "";
  }
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function init() {
  try {
    await getMe();
  } catch (_) {
    window.location.replace(loginPath());
    return;
  }

  let injuriesByPlayer = {};
  try {
    const meta = await getMetaWeek();
    week = meta.week;
    lineupTitle.textContent = `Gameweek ${week} Lineup`;
    if (meta.opponents_by_team) {
      roster.setOpponentsByTeam(meta.opponents_by_team);
    }
    injuriesByPlayer = meta.injuries_by_player || {};
  } catch (_) {
    lineupTitle.textContent = "Gameweek 1 Lineup";
  }
  try {
    const saved = await getRoster();
    if (saved) roster.loadFromSaved(saved);
  } catch (_) {}
  // After roster slots exist so left-panel cards show focus-week injury labels
  if (Object.keys(injuriesByPlayer).length) {
    roster.setInjuries(injuriesByPlayer);
  }
}

init();
