/** Render True Depth Chart as a flat QB / RB / WR / TE table. */

const COLUMN_ORDER = ["QB", "RB", "WR", "TE"];
const INJURY_MARKS = new Set(["O", "D", "Q"]);
const TRUE_ELIGIBLE = new Set(["RB", "WR", "TE"]);

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function injuryHtml(mark) {
  if (!mark || !INJURY_MARKS.has(mark)) return "";
  return ` <span class="tdc-injury">(${escapeHtml(mark)})</span>`;
}

function opportunityHtml(pct, bellcow) {
  const bell = bellcow
    ? ' <span class="tdc-bellcow" aria-label="Bellcow">🔔</span>'
    : "";
  if (pct == null || Number.isNaN(Number(pct))) {
    return bell;
  }
  const formatted = Number(pct).toFixed(1);
  return `${bell} <span class="tdc-opp">(${escapeHtml(formatted)}%)</span>`;
}

function movementArrow(movement) {
  if (movement === "up") {
    return '<span class="tdc-move is-up" aria-label="Moved up">▲</span>';
  }
  if (movement === "down") {
    return '<span class="tdc-move is-down" aria-label="Moved down">▼</span>';
  }
  return "";
}

function resolveCell(entry, trueMode, eligible) {
  if (trueMode && eligible && entry?.true) {
    return {
      player_name: entry.true.player_name ?? null,
      injury_mark: entry.true.injury_mark ?? null,
      movement: entry.true.movement || "none",
      opportunity_pct: entry.true.opportunity_pct ?? null,
      bellcow: Boolean(entry.true.bellcow),
    };
  }
  const published = entry?.published || {};
  return {
    player_name: published.player_name ?? null,
    injury_mark: published.injury_mark ?? null,
    movement: "none",
    opportunity_pct: null,
    bellcow: false,
  };
}

function renderCell(entry, trueMode, eligible) {
  const cell = resolveCell(entry, trueMode, eligible);
  const classes = ["tdc-cell"];
  if (!cell.player_name) classes.push("is-empty");
  if (trueMode && eligible) {
    if (cell.movement === "up") classes.push("is-up");
    if (cell.movement === "down") classes.push("is-down");
  }

  if (!cell.player_name) {
    return `<td class="${classes.join(" ")}"></td>`;
  }

  const arrow = trueMode && eligible ? movementArrow(cell.movement) : "";
  const opp =
    trueMode && eligible
      ? opportunityHtml(cell.opportunity_pct, cell.bellcow)
      : "";
  return `<td class="${classes.join(" ")}">
    <span class="tdc-player">${arrow}<span class="tdc-name">${escapeHtml(cell.player_name)}</span>${opp}${injuryHtml(cell.injury_mark)}</span>
  </td>`;
}

/**
 * @param {object} payload — team chart payload with `columns`
 * @param {boolean} trueMode
 * @returns {string} HTML
 */
export function renderTrueDepthChart(payload, trueMode) {
  const columns = payload?.columns || {};
  const lists = COLUMN_ORDER.map((pos) => columns[pos] || []);
  const maxRows = Math.max(0, ...lists.map((list) => list.length));
  if (maxRows === 0) {
    return `<p class="empty-hint">No depth chart data for this team.</p>`;
  }

  const head = COLUMN_ORDER.map(
    (pos) => `<th scope="col">${escapeHtml(pos)}</th>`
  ).join("");

  const body = [];
  for (let row = 0; row < maxRows; row++) {
    const cells = COLUMN_ORDER.map((pos, i) => {
      const entry = lists[i][row] || null;
      return renderCell(entry, trueMode, TRUE_ELIGIBLE.has(pos));
    }).join("");
    body.push(`<tr>${cells}</tr>`);
  }

  return `<div class="tdc-table-wrap">
    <table class="tdc-table atlas-table tdc-skill-table">
      <thead><tr>${head}</tr></thead>
      <tbody>${body.join("")}</tbody>
    </table>
  </div>`;
}

const INJURY_UNITS = ["OL", "DL", "LBs", "DBs"];

/** Fill the Other Starter Injuries rail from payload.other_starter_injuries. */
export function renderOtherStarterInjuries(counts) {
  const data = counts || {};
  for (const unit of INJURY_UNITS) {
    const el = document.querySelector(`.tdc-injuries-count[data-unit="${unit}"]`);
    if (el) el.textContent = String(data[unit] ?? 0);
  }
}
