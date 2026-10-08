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

  // Live activity: server-sent events while the agents are working. While the
  // stream is connected the activity panel's 2-second polling pauses
  // (window.ndLive); if the stream drops, polling takes over again.
  function refreshActivity() {
    if (window.htmx && document.getElementById("nd-activity")) {
      window.htmx.ajax("GET", root.dataset.activity, { target: "#nd-activity", swap: "outerHTML" });
    }
  }

  // Real models stream structured output as JSON; show it as plain words.
  function readable(text) {
    return text
      .replace(/\\n/g, " ")
      .replace(/"[a-z_]+"\s*:\s*/g, "")
      .replace(/[{}\[\]"]/g, "")
      .replace(/,\s*(?=\S)/g, ", ");
  }

  function onEvent(event) {
    if (event.kind === "run_end") {
      window.location.reload();
      return true;
    }
    if (event.kind === "text") {
      const box = root.querySelector(`[data-step-stream="${event.step}"]`);
      if (box) {
        box.hidden = false;
        box.textContent = (box.textContent + readable(event.message)).slice(-2000);
        box.scrollTop = box.scrollHeight;
      }
      return false;
    }
    const list = event.step && root.querySelector(`[data-step-events="${event.step}"]`);
    if (list && !["step", "step_done"].includes(event.kind)) {
      const item = document.createElement("li");
      item.textContent = event.message;
      list.appendChild(item);
    } else {
      refreshActivity(); // a step started or finished: redraw the panel
    }
    const badge = document.getElementById("nd-status");
    if (badge && event.kind === "step") {
      badge.textContent = "Agents working";
      badge.className = "nd-status nd-status--working";
    }
    return false;
  }

  if (root.dataset.events && "EventSource" in window) {
    const source = new EventSource(root.dataset.events);
    source.onopen = () => (window.ndLive = true);
    source.onerror = () => (window.ndLive = false);
    source.onmessage = (message) => {
      if (onEvent(JSON.parse(message.data))) source.close();
    };
  }

  window.ndWorkspace = { root, showTab, onEvent };
})();
