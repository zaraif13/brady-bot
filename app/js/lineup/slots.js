/** Shared lineup slot display labels (not NFL depth-chart roles).
 *
 * Internal keys RB1/WR2 are opaque lineup indices for the API/saved roster —
 * they are NOT depth-chart roles. Display always uses unnumbered slots.
 */

/** Internal starter keys → UI label. Duplicate RBs/WRs both show "RB"/"WR". */
export const LINEUP_SLOT_LABELS = {
  QB: "QB",
  RB1: "RB",
  RB2: "RB",
  WR1: "WR",
  WR2: "WR",
  TE: "TE",
  FLEX: "FLEX",
  DEF: "D/ST",
  K: "K",
};

/**
 * @param {string} slotKey internal key e.g. RB1, DEF, BN3
 * @returns {string} display label
 */
export function slotLabel(slotKey) {
  if (!slotKey) return "";
  if (LINEUP_SLOT_LABELS[slotKey]) return LINEUP_SLOT_LABELS[slotKey];
  if (slotKey.startsWith("BN")) return "BN";
  if (slotKey.startsWith("IR")) return "IR";
  if (slotKey === "DST" || slotKey === "D/ST") return "D/ST";
  return String(slotKey).replace(/\d+$/, "");
}

/** @deprecated use slotLabel */
export const lineupSlotLabel = slotLabel;
