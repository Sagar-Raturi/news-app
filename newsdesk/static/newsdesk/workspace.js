// AI article workspace: tab switching without a reload. Every tab is also a
// plain link (?tab=...), so the page works without JavaScript.
(function () {
  "use strict";

  const root = document.querySelector(".nd-workspace");
  if (!root) return;

  function showTab(name, push) {
    const tabs = root.querySelectorAll(".nd-tabs [data-tab]");
    if (![...tabs].some((t) => t.dataset.tab === name)) return;
    tabs.forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
    root.querySelectorAll(".nd-panel").forEach((p) => (p.hidden = p.dataset.panel !== name));
    if (push) {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", name);
      window.history.replaceState({}, "", url);
    }
  }

  root.querySelector(".nd-tabs")?.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-tab]");
    if (!tab) return;
    event.preventDefault();
    showTab(tab.dataset.tab, true);
  });

  // Confirm destructive or public actions (forms carry data-confirm).
  root.addEventListener("submit", (event) => {
    const message = event.target.dataset?.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });

  window.ndWorkspace = { root, showTab };
})();
