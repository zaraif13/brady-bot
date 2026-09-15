/** Render the Brady Bot nav from the section registry. */
import { sectionPath } from "./api.js";
import { SECTIONS } from "./sections.js";

export function renderNav() {
  for (const nav of document.querySelectorAll("[data-nav-root]")) {
    const activeId = nav.dataset.navActive;
    nav.innerHTML = SECTIONS.map((section) => {
      const active = section.id === activeId ? " is-active" : "";
      return `<a class="atlas-tab${active}" href="${sectionPath(section)}">${section.label}</a>`;
    }).join("");
  }
}
