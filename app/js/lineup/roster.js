import { searchPlayers } from "../api.js";
import { renderPlayerCard } from "./cards.js";
import { slotLabel } from "./slots.js";

/**
 * keys are opaque lineup indices (not depth-chart roles).
 * Display order: QB, RB, RB, WR, WR, TE, D/ST, K, FLEX — then BN / IR.
 */
const BASE_STARTER_SLOTS = [
  { key: "QB", label: "QB", filter: "QB", deletable: false },
  { key: "RB1", label: "RB", filter: "RB", deletable: false },
  { key: "RB2", label: "RB", filter: "RB", deletable: false },
  { key: "WR1", label: "WR", filter: "WR", deletable: false },
  { key: "WR2", label: "WR", filter: "WR", deletable: false },
  { key: "TE", label: "TE", filter: "TE", deletable: false },
  { key: "DEF", label: "D/ST", filter: "DEF", deletable: false },
  { key: "K", label: "K", filter: "K", deletable: false },
  { key: "FLEX", label: "FLEX", filter: "FLEX", deletable: false },
];

export function createRosterController(rootEl, { onChange } = {}) {
  const state = {
    slots: [],
    bnExtra: 0,
    irExtra: 0,
    opponentsByTeam: {},
    injuriesByPlayer: {},
  };

  function opponentFor(player) {
    if (!player?.team) return "—";
    const opp = state.opponentsByTeam[player.team];
    return opp !== undefined ? opp : "—";
  }

  function withCardMeta(player) {
    if (!player) return player;
    const injury = state.injuriesByPlayer[player.player_id];
    return {
      ...player,
      opponent: opponentFor(player),
      injury_status: injury || player.injury_status || undefined,
    };
  }

  function rebuildSlots() {
    const slots = [...BASE_STARTER_SLOTS.map((s) => ({ ...s, player: null }))];
    for (let i = 0; i < 6 + state.bnExtra; i++) {
      slots.push({
        key: `BN${i + 1}`,
        label: "BN",
        filter: "BN",
        deletable: i >= 6,
        player: state.slots.find((x) => x.key === `BN${i + 1}`)?.player || null,
      });
    }
    for (let i = 0; i < state.irExtra; i++) {
      slots.push({
        key: `IR${i + 1}`,
        label: "IR",
        filter: "IR",
        deletable: true,
        player: state.slots.find((x) => x.key === `IR${i + 1}`)?.player || null,
      });
    }
    for (const base of BASE_STARTER_SLOTS) {
      const prev = state.slots.find((x) => x.key === base.key);
      const cur = slots.find((x) => x.key === base.key);
      if (prev?.player && cur) cur.player = prev.player;
    }
    state.slots = slots;
  }

  function getPlayers() {
    return state.slots.filter((s) => s.player).map((s) => ({ slot: s.key, ...s.player }));
  }

  function render() {
    rootEl.innerHTML = "";
    for (const slot of state.slots) {
      const row = document.createElement("div");
      row.className = "slot-row";
      row.dataset.key = slot.key;

      const label = document.createElement("div");
      label.className = "slot-label";
      label.textContent = slot.label || slotLabel(slot.key);

      const body = document.createElement("div");
      body.className = "slot-body";

      if (slot.player) {
        body.innerHTML = renderPlayerCard(withCardMeta(slot.player), "is-empty-border");
        const clear = document.createElement("button");
        clear.type = "button";
        clear.className = "atlas-btn atlas-btn-ghost atlas-btn-sm slot-clear";
        clear.textContent = "Clear";
        clear.addEventListener("click", () => {
          slot.player = null;
          render();
          onChange?.(getPlayers());
        });
        body.appendChild(clear);
      } else {
        const input = document.createElement("input");
        input.className = "atlas-input slot-input";
        input.placeholder = `Search ${slot.label}…`;
        input.autocomplete = "off";
        const dropdown = document.createElement("div");
        dropdown.className = "autocomplete";
        dropdown.hidden = true;
        let timer = null;

        input.addEventListener("input", () => {
          clearTimeout(timer);
          const q = input.value.trim();
          if (q.length < 2) {
            dropdown.hidden = true;
            dropdown.innerHTML = "";
            return;
          }
          timer = setTimeout(async () => {
            try {
              const results = await searchPlayers(q, slot.filter);
              dropdown.innerHTML = "";
              if (!results.length) {
                dropdown.hidden = true;
                return;
              }
              for (const p of results) {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "autocomplete-item";
                btn.innerHTML = `<span>${escapeHtml(p.name)}</span><span class="autocomplete-meta">${escapeHtml(p.position)} ${escapeHtml(p.team)}</span>`;
                btn.addEventListener("click", () => {
                  slot.player = withCardMeta(p);
                  render();
                  onChange?.(getPlayers());
                });
                dropdown.appendChild(btn);
              }
              dropdown.hidden = false;
            } catch (e) {
              console.error(e);
            }
          }, 180);
        });

        body.appendChild(input);
        body.appendChild(dropdown);
      }

      row.appendChild(label);
      row.appendChild(body);

      const actions = document.createElement("div");
      if (slot.deletable) {
        const del = document.createElement("button");
        del.type = "button";
        del.className = "atlas-btn atlas-btn-ghost atlas-btn-sm";
        del.textContent = "✕";
        del.title = "Remove slot";
        del.addEventListener("click", () => {
          if (slot.key.startsWith("BN")) {
            state.bnExtra = Math.max(0, state.bnExtra - 1);
          } else if (slot.key.startsWith("IR")) {
            state.irExtra = Math.max(0, state.irExtra - 1);
          }
          rebuildSlots();
          render();
          onChange?.(getPlayers());
        });
        actions.appendChild(del);
      }
      row.appendChild(actions);
      rootEl.appendChild(row);
    }
  }

  function addBn() {
    state.bnExtra += 1;
    rebuildSlots();
    render();
  }

  function addIr() {
    state.irExtra += 1;
    rebuildSlots();
    render();
  }

  function reset() {
    for (const slot of state.slots) {
      slot.player = null;
    }
    render();
    onChange?.(getPlayers());
  }

  function setOpponentsByTeam(map) {
    state.opponentsByTeam = map || {};
    for (const slot of state.slots) {
      if (slot.player) slot.player = withCardMeta(slot.player);
    }
    render();
  }

  function setInjuries(map) {
    state.injuriesByPlayer = map || {};
    for (const slot of state.slots) {
      if (slot.player) slot.player = withCardMeta(slot.player);
    }
    render();
  }

  function loadFromSaved(saved) {
    if (!saved?.slots) return;
    state.bnExtra = saved.bn_extra || 0;
    state.irExtra = saved.ir_extra || 0;
    rebuildSlots();
    for (const entry of saved.slots) {
      const slot = state.slots.find((s) => s.key === entry.slot);
      if (slot && entry.player) slot.player = withCardMeta(entry.player);
    }
    render();
  }

  /** @deprecated prefer setOpponentsByTeam; kept for pick-result player_id maps */
  function setOpponents(oppMap) {
    for (const slot of state.slots) {
      if (slot.player && oppMap[slot.player.player_id] !== undefined) {
        slot.player.opponent = oppMap[slot.player.player_id];
      }
    }
    render();
  }

  rebuildSlots();
  render();

  return {
    addBn,
    addIr,
    reset,
    getPlayers,
    getState: () => ({
      bn_extra: state.bnExtra,
      ir_extra: state.irExtra,
      slots: state.slots.map((s) => ({
        slot: s.key,
        player: s.player,
      })),
    }),
    loadFromSaved,
    setOpponents,
    setOpponentsByTeam,
    setInjuries,
  };
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
