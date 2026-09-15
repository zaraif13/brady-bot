/** Nav-bar Refresh button — force nflverse sources to refetch now. */
import { refreshData } from "./api.js";

const btn = document.getElementById("btn-refresh");

btn?.addEventListener("click", async () => {
  if (btn.disabled) return;
  btn.disabled = true;
  btn.classList.add("is-loading");
  try {
    await refreshData();
    window.location.reload();
  } catch (err) {
    btn.disabled = false;
    btn.classList.remove("is-loading");
    alert(err.message || "Refresh failed");
  }
});
