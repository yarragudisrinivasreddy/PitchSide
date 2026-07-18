/* PitchSide frontend — vanilla JS, CSP-compliant (no inline handlers). */

"use strict";

function persona() {
  const checked = document.querySelector('input[name="persona"]:checked');
  return checked ? checked.value : "fan";
}

function show(el, text) {
  el.textContent = text;
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || "Request failed");
  }
  return data;
}

function renderAssist(target, data) {
  const lines = [];
  lines.push("Intent: " + data.intent + " (" + data.source + ")");
  if (data.guidance) {
    lines.push("");
    lines.push(data.guidance);
  }
  if (data.result && data.result.segments) {
    lines.push("");
    lines.push(
      "Route: " +
        data.result.total_distance_m +
        " m, ~" +
        data.result.eta_minutes +
        " min" +
        (data.result.fully_step_free ? " (fully step-free)" : "")
    );
    data.result.segments.forEach(function (seg) {
      lines.push(
        "  " +
          seg.from +
          " -> " +
          seg.to +
          " (" +
          seg.distance_m +
          " m" +
          (seg.step_free ? "" : ", stairs") +
          ")"
      );
    });
  }
  show(target, lines.join("\n"));
}

function wireAssistForm() {
  const form = document.getElementById("assist-form");
  const result = document.getElementById("assist-result");
  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    show(result, "Working…");
    try {
      const data = await postJson("/api/assist", {
        message: document.getElementById("message").value,
        persona: persona(),
        language: document.getElementById("language").value,
      });
      renderAssist(result, data);
    } catch (error) {
      show(result, "Sorry — " + error.message);
    }
  });
}

function wireChips() {
  document.querySelectorAll(".chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      const box = document.getElementById("message");
      box.value = chip.getAttribute("data-fill");
      box.focus();
    });
  });
}

async function refreshZones() {
  const list = document.getElementById("zones-list");
  const response = await fetch("/api/zones");
  const data = await response.json();
  list.replaceChildren();
  data.zones.forEach(function (zone) {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = zone.zone;
    const status = document.createElement("span");
    status.className = "status-" + zone.status;
    status.textContent =
      zone.status +
      " · density " +
      zone.density +
      " · ~" +
      zone.estimated_concession_wait_min +
      " min wait";
    item.append(name, status);
    list.append(item);
  });
}

async function refreshOps() {
  const panel = document.getElementById("ops-panel");
  const response = await fetch("/api/ops/summary");
  const data = await response.json();
  const lines = [];
  lines.push("Open incidents: " + data.open_incident_count);
  lines.push(
    "P1: " +
      data.incidents_by_severity.P1 +
      "  P2: " +
      data.incidents_by_severity.P2 +
      "  P3: " +
      data.incidents_by_severity.P3
  );
  lines.push("");
  lines.push("Recommended actions:");
  data.recommended_actions.forEach(function (action) {
    lines.push("  • " + action);
  });
  show(panel, lines.join("\n"));
}

function applyLanguageDirection() {
  const code = document.getElementById("language").value;
  const result = document.getElementById("assist-result");
  result.setAttribute("lang", code);
  result.setAttribute("dir", code === "ar" ? "rtl" : "ltr");
}

document.addEventListener("DOMContentLoaded", function () {
  document
    .getElementById("language")
    .addEventListener("change", applyLanguageDirection);
  applyLanguageDirection();
  wireAssistForm();
  wireChips();
  document.getElementById("refresh-zones").addEventListener("click", refreshZones);
  document.getElementById("refresh-ops").addEventListener("click", refreshOps);
  refreshZones();
});
