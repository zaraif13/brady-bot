/** Render Opportunity Share table for one team. */

/** WR/TE target share: red <8%, neutral 8–16%, green >16%. */
const TARGET_SHARE_LOW = 8;
const TARGET_SHARE_HIGH = 16;
/** RB rush share: red <40%, neutral 40–60%, green (bellcow) ≥60%. */
const RUSH_SHARE_LOW = 40;
const RUSH_SHARE_HIGH = 60;

const TARGET_POSITIONS = new Set(["WR", "TE"]);
const RUSH_POSITIONS = new Set(["RB"]);

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatPct(pct) {
  if (pct == null || Number.isNaN(Number(pct))) return null;
  return Number(pct).toFixed(1);
}

/**
 * @param {number} pct
 * @param {"target"|"rush"} metric
 * @returns {"low"|"mid"|"high"|null}
 */
export function shareTone(pct, metric) {
  if (pct == null || Number.isNaN(Number(pct))) return null;
  const n = Number(pct);
  if (metric === "target") {
    if (n < TARGET_SHARE_LOW) return "low";
    if (n > TARGET_SHARE_HIGH) return "high";
    return "mid";
  }
  if (metric === "rush") {
    if (n < RUSH_SHARE_LOW) return "low";
    if (n >= RUSH_SHARE_HIGH) return "high";
    return "mid";
  }
  return null;
}

/**
 * @param {string|null|undefined} position
 * @param {"target"|"rush"} metric
 * @param {number|null|undefined} pct
 * @returns {"low"|"mid"|"high"|null}
 */
function toneForRow(position, metric, pct) {
  const pos = String(position || "").toUpperCase();
  if (metric === "target" && !TARGET_POSITIONS.has(pos)) return null;
  if (metric === "rush" && !RUSH_POSITIONS.has(pos)) return null;
  return shareTone(pct, metric);
}

/**
 * @param {number|null|undefined} pct
 * @param {number|null|undefined} qty
 * @param {"low"|"mid"|"high"|null} tone
 * @returns {string}
 */
function metricCell(pct, qty, tone) {
  const formatted = formatPct(pct);
  if (formatted == null) {
    return `<td class="opp-metric is-na"><span class="opp-na">—</span></td>`;
  }
  const width = Math.max(0, Math.min(100, Number(pct)));
  const toneClass = tone ? ` opp-tone-${tone}` : "";
  const qtyHtml =
    qty == null
      ? ""
      : ` <span class="opp-qty">(${escapeHtml(String(qty))})</span>`;
  return `<td class="opp-metric${toneClass}">
    <div class="opp-metric-inner">
      <div class="opp-bar-track" aria-hidden="true">
        <div class="opp-bar-fill" style="width:${width}%"></div>
      </div>
      <span class="opp-pct">${escapeHtml(formatted)}%</span>${qtyHtml}
    </div>
  </td>`;
}

function playerCell(row, showGp) {
  const gp =
    showGp && row.gp != null
      ? ` <span class="opp-gp" title="Target weeks: ${escapeHtml(
          String(row.gp_tgt ?? "—")
        )} · Rush weeks: ${escapeHtml(String(row.gp_rsh ?? "—"))}">GP ${escapeHtml(
          String(row.gp)
        )}</span>`
      : "";
  const bell = row.bellcow
    ? ' <span class="opp-bellcow" aria-label="Bellcow">🔔</span>'
    : "";
  return `<td class="opp-player-cell">
    <span class="opp-player-name">${escapeHtml(row.player)}</span>${gp}${bell}
  </td>`;
}

function rzMixNote(rzMix) {
  if (!rzMix || !rzMix.rz_plays) {
    return "no RZ plays yet";
  }
  const passPct = formatPct(rzMix.rz_pass_pct) ?? "—";
  const rushPct = formatPct(rzMix.rz_rush_pct) ?? "—";
  return `RZ mix ${escapeHtml(passPct)}% pass / ${escapeHtml(rushPct)}% rush (${escapeHtml(
    String(rzMix.rz_plays)
  )} plays)`;
}

/**
 * @param {object} payload
 * @returns {string} HTML
 */
export function renderOpportunityShareTable(payload) {
  const rows = payload?.rows || [];
  if (!rows.length) {
    return `<p class="empty-hint">No opportunity share data for this team.</p>`;
  }

  const showGp = payload.view === "all";
  const seasonLabel = escapeHtml(payload.season_group_label || "Season");
  const mixNote = rzMixNote(payload.rz_mix);

  const body = rows
    .map((row) => {
      const pos = row.position;
      return `<tr>
      ${playerCell(row, showGp)}
      <td class="opp-pos">${escapeHtml(pos || "")}</td>
      ${metricCell(row.target_share_pct, row.targets, toneForRow(pos, "target", row.target_share_pct))}
      ${metricCell(row.rush_share_pct, row.carries, toneForRow(pos, "rush", row.rush_share_pct))}
      ${metricCell(row.rz_target_share_pct, row.rz_targets, toneForRow(pos, "target", row.rz_target_share_pct))}
      ${metricCell(row.rz_rush_share_pct, row.rz_carries, toneForRow(pos, "rush", row.rz_rush_share_pct))}
    </tr>`;
    })
    .join("");

  return `<div class="opp-table-scroll">
    <table class="opp-table">
      <thead>
        <tr class="opp-head-groups">
          <th scope="col" colspan="2" class="opp-corner"></th>
          <th scope="colgroup" colspan="2" class="opp-group-season">${seasonLabel}</th>
          <th scope="colgroup" colspan="2" class="opp-group-rz">Red Zone</th>
        </tr>
        <tr class="opp-head-cols">
          <th scope="col">Player</th>
          <th scope="col">Pos</th>
          <th scope="col">Target Share</th>
          <th scope="col">Rush Share</th>
          <th scope="col">RZ Target Share</th>
          <th scope="col">RZ Rush Share</th>
        </tr>
        <tr class="opp-head-note">
          <th colspan="4"></th>
          <th colspan="2" class="opp-rz-note">${mixNote}</th>
        </tr>
      </thead>
      <tbody>${body}</tbody>
    </table>
  </div>`;
}
