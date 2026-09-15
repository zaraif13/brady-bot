/** Player card rendering. */

const PLACEHOLDER =
  "data:image/svg+xml," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect fill="#171717" width="40" height="40"/><text x="50%" y="54%" fill="#777" font-size="10" text-anchor="middle" font-family="sans-serif">NFL</text></svg>`
  );

function fmt2(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return "—";
  return x.toFixed(2);
}

/**
 * One factor equation block (positional Start Score or FLEX Score).
 * @param {{ title: string, factors: array, weighted_sum?: number, bonus?: number, flags?: array, start_score?: number, scoreLabel?: string }} opts
 */
function renderEquationBlock(opts = {}) {
  const factors = Array.isArray(opts.factors) ? opts.factors : [];
  if (!factors.length) return "";

  const title = opts.title || "Start Score equation";
  const scoreLabel = opts.scoreLabel || "Start Score";
  const tier2Bonus = Number(opts.bonus) || 0;
  const flags = Array.isArray(opts.flags) ? opts.flags : [];
  const startScore = opts.start_score;
  const weightedSum = opts.weighted_sum;

  let sum = 0;
  const rows = factors
    .map((f) => {
      const score = Number(f.score) || 0;
      const weight = Number(f.weight) || 0;
      const contrib = score * weight;
      sum += contrib;
      const input = f.raw_value != null && f.raw_value !== "" ? String(f.raw_value) : "—";
      return `<tr>
          <td class="col-factor">${escapeHtml(f.name || "—")}</td>
          <td class="col-input">${escapeHtml(input)}</td>
          <td class="col-num">${fmt2(score)}</td>
          <td class="col-num">${fmt2(weight)}</td>
          <td class="col-num">${fmt2(contrib)}</td>
        </tr>`;
    })
    .join("");

  const factorTotal =
    weightedSum != null && Number.isFinite(Number(weightedSum))
      ? Number(weightedSum)
      : sum;
  const total =
    startScore != null && Number.isFinite(Number(startScore))
      ? Number(startScore)
      : factorTotal;

  let html = `
      <div class="details-equation">
        <div class="details-equation-title">${escapeHtml(title)}</div>
        <table class="details-factor-table">
          <thead>
            <tr>
              <th>Factor</th>
              <th>Input</th>
              <th>Score</th>
              <th>Weight</th>
              <th>Contribution</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="details-combine">
          Weighted sum = Σ (score × weight) = <strong>${fmt2(factorTotal)}</strong>
        </div>`;
  if (tier2Bonus > 0 || flags.includes("tier2_bonus")) {
    html += `<div class="details-combine">
          Tier 2 bonus = <strong>+${fmt2(tier2Bonus || 0.3)}</strong>${
            flags.includes("score_capped") ? " (capped at 1.00)" : ""
          }
        </div>`;
  }
  html += `<div class="details-combine">
          ${escapeHtml(scoreLabel)} = <strong>${fmt2(total)}</strong>
        </div>
      </div>`;
  return html;
}

/**
 * Build HTML for the expandable details panel (why + optional equation work).
 * Bench leftovers that lost RB/WR/TE then FLEX carry prior_* fields for a second equation.
 */
export function renderDetailsPanelBody(opts = {}) {
  const explain = opts.explanation || "";
  const factors = Array.isArray(opts.factors) ? opts.factors : [];
  const gate = opts.gate_result || "";
  const gateReason = opts.gate_reason || "";
  const startScore = opts.start_score;
  const priorFactors = Array.isArray(opts.prior_factors) ? opts.prior_factors : [];
  const priorLabel = opts.prior_label || "";

  let html = `<div class="details-why">${escapeHtml(explain || "No details available.")}</div>`;

  if (gate === "auto_start" && factors.length === 0 && priorFactors.length === 0) {
    html += `<div class="details-gate">Auto-start — equation not applied${
      gateReason ? ` (${escapeHtml(gateReason)})` : ""
    }.</div>`;
  } else if (gate === "eliminated" && factors.length === 0 && priorFactors.length === 0) {
    html += `<div class="details-gate">Eliminated — not scored${
      gateReason ? ` (${escapeHtml(gateReason)})` : ""
    }.</div>`;
  }

  const hasDual = priorFactors.length > 0;

  if (hasDual) {
    html += renderEquationBlock({
      title: `${priorLabel || "Position"} Start Score equation`,
      factors: priorFactors,
      weighted_sum: opts.prior_weighted_sum,
      bonus: opts.prior_bonus,
      flags: opts.prior_flags,
      start_score: opts.prior_start_score,
      scoreLabel: "Start Score",
    });
    html += renderEquationBlock({
      title: "FLEX Score equation",
      factors,
      weighted_sum: opts.weighted_sum,
      bonus: opts.bonus,
      flags: opts.flags,
      start_score: startScore,
      scoreLabel: "FLEX Score",
    });
  } else if (factors.length > 0) {
    html += renderEquationBlock({
      title: "Start Score equation",
      factors,
      weighted_sum: opts.weighted_sum,
      bonus: opts.bonus,
      flags: opts.flags,
      start_score: startScore,
      scoreLabel: "Start Score",
    });
  } else if (
    gate === "passed" ||
    (startScore != null && factors.length === 0 && gate !== "auto_start" && gate !== "eliminated")
  ) {
    if (explain && (gate === "passed" || startScore != null)) {
      html += `<div class="details-gate">No factor breakdown available.</div>`;
    }
  }

  return html;
}

/**
 * @param {object} player
 * @param {string} borderClass
 * @param {object} [opts]
 */
export function renderPlayerCard(player, borderClass = "is-bench", opts = {}) {
  const img = player.headshot || PLACEHOLDER;
  const opp = player.opponent
    ? player.opponent === "BYE"
      ? "BYE"
      : `vs ${player.opponent}`
    : "—";
  const pid = escapeAttr(player.player_id || "");
  const injury =
    opts.injury_status || player.injury_status
      ? `<span class="injury-status">${escapeHtml(opts.injury_status || player.injury_status)}</span>`
      : "";

  if (opts.details) {
    const panelId = `details-${pid || "empty"}`;
    const body = renderDetailsPanelBody({
      explanation: opts.explanation || player.explanation || "",
      start_score: opts.start_score ?? player.start_score,
      factors: opts.factors ?? player.factors,
      gate_result: opts.gate_result ?? player.gate_result,
      gate_reason: opts.gate_reason ?? player.gate_reason,
      weighted_sum: opts.weighted_sum ?? player.weighted_sum,
      bonus: opts.bonus ?? player.bonus,
      flags: opts.flags ?? player.flags,
      prior_label: opts.prior_label ?? player.prior_label,
      prior_start_score: opts.prior_start_score ?? player.prior_start_score,
      prior_weighted_sum: opts.prior_weighted_sum ?? player.prior_weighted_sum,
      prior_bonus: opts.prior_bonus ?? player.prior_bonus,
      prior_flags: opts.prior_flags ?? player.prior_flags,
      prior_factors: opts.prior_factors ?? player.prior_factors,
    });
    return `
    <div class="lineup-card-wrap">
      <div class="player-card ${borderClass} has-details" data-player-id="${pid}">
        <img class="headshot" src="${img}" alt="" loading="lazy"
             onerror="this.src='${PLACEHOLDER}'" />
        <div class="card-body">
          <div class="name">${escapeHtml(player.name)}${injury ? ` ${injury}` : ""}</div>
          <div class="meta">${escapeHtml(player.position)} · ${escapeHtml(player.team)} · ${escapeHtml(opp)}</div>
        </div>
        <button type="button" class="card-details-toggle" aria-expanded="false" aria-controls="${panelId}">
          details <span class="chevron" aria-hidden="true">▾</span>
        </button>
      </div>
      <div class="card-details-panel" id="${panelId}" hidden>${body}</div>
    </div>
  `;
  }

  return `
    <div class="player-card ${borderClass}" data-player-id="${pid}">
      <img class="headshot" src="${img}" alt="" loading="lazy"
           onerror="this.src='${PLACEHOLDER}'" />
      <div>
        <div class="name">${escapeHtml(player.name)}${injury ? ` ${injury}` : ""}</div>
        <div class="meta">${escapeHtml(player.position)} · ${escapeHtml(player.team)} · ${escapeHtml(opp)}</div>
      </div>
    </div>
  `;
}

/**
 * Empty lineup slot with details disclosure.
 * @param {string} [explanation]
 * @param {string} [idSuffix]
 */
export function renderEmptyLineupCard(
  explanation = "No eligible player for this slot.",
  idSuffix = "empty"
) {
  const panelId = `details-${escapeAttr(idSuffix)}`;
  const body = renderDetailsPanelBody({ explanation });
  return `
    <div class="lineup-card-wrap">
      <div class="player-card is-empty-border has-details">
        <div class="card-body">
          <div class="name">EMPTY</div>
          <div class="meta">No eligible player</div>
        </div>
        <button type="button" class="card-details-toggle" aria-expanded="false" aria-controls="${panelId}">
          details <span class="chevron" aria-hidden="true">▾</span>
        </button>
      </div>
      <div class="card-details-panel" id="${panelId}" hidden>${body}</div>
    </div>
  `;
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(s) {
  return escapeHtml(s).replaceAll("'", "&#39;");
}
