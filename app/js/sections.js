/**
 * Brady Bot section registry — the single source of truth for the nav bar.
 *
 * Adding a section: create its page, add `js/<id>/`, `docs/<id>/` and any
 * `/api/<id>/` routes, then append one entry here. Nothing else renders nav.
 */
export const SECTIONS = [
  { id: "lineup", label: "Lineup Picker", page: "index.html", route: "/" },
  { id: "depth-chart", label: "True Depth Chart", page: "true-depth.html", route: "/true-depth" },
  { id: "opportunity", label: "Opportunity Share", page: "opportunity-share.html", route: "/opportunity-share" },
];
