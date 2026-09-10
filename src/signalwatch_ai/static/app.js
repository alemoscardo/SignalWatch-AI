const data = JSON.parse(document.querySelector("#demo-data").textContent);
let sensor = "temperature";
let selected = data.alerts.length ? 0 : null;
const chart = document.querySelector("#chart");
const alertButtons = document.querySelectorAll("[data-alert]");
const sensorButtons = document.querySelectorAll("[data-sensor]");
const selection = document.querySelector("#selection");
const investigateButton = document.querySelector("#investigate");
const context = document.querySelector("#context");
const report = document.querySelector("#report");
const status = document.querySelector("#ai-status");
const trace = document.querySelector("#trace");
const tracePanel = document.querySelector("#trace-panel");
const ready = !investigateButton.disabled;
const idleStatus = status.textContent;
const idleButton = investigateButton.innerHTML;
const search = document.querySelector("#search");
const searchButton = search.querySelector("button");
const query = document.querySelector("#query");
const searchStatus = document.querySelector("#search-status");
const results = document.querySelector("#results");

function clearInvestigation() {
  report.replaceChildren();
  trace.replaceChildren();
  tracePanel.hidden = true;
  tracePanel.open = false;
  status.textContent = idleStatus;
}

function setInvestigating(active) {
  investigateButton.disabled = active || !ready || selected === null;
  investigateButton.classList.toggle("generating", active);
  investigateButton.innerHTML = active
    ? '<span class="loading-spinner" aria-hidden="true"></span> Generating…'
    : idleButton;
  report.setAttribute("aria-busy", String(active));
  alertButtons.forEach((button) => (button.disabled = active));
  context.disabled = active;
}

function renderDocuments(documents, expanded = false) {
  results.replaceChildren();
  for (const doc of documents) {
    const details = document.createElement("details");
    details.id = doc.id;
    details.open = expanded;
    const summary = document.createElement("summary");
    summary.textContent = doc.section;
    const title = document.createElement("small");
    title.textContent = doc.title;
    summary.append(title);
    const text = document.createElement("p");
    text.textContent = doc.text;
    const reference = document.createElement("small");
    reference.textContent = doc.document;
    details.append(summary, text, reference);
    results.append(details);
  }
}

const svgNS = "http://www.w3.org/2000/svg";

function svgElement(name, attributes, text = "") {
  const element = document.createElementNS(svgNS, name);
  for (const [key, value] of Object.entries(attributes))
    element.setAttribute(key, value);
  element.textContent = text;
  chart.append(element);
  return element;
}

function drawChart() {
  chart.replaceChildren();
  const rows = data[sensor];
  if (!rows.length) {
    svgElement(
      "text",
      { x: 70, y: 100, fill: "#637578" },
      "No measurements available",
    );
    return;
  }
  const values = rows.map((row) => row.value);
  const low = Math.floor((Math.min(...values) - 5) / 10) * 10;
  const high =
    Math.ceil(
      (Math.max(
        ...values,
        ...(sensor === "temperature" ? [data.threshold] : []),
      ) +
        5) /
        10,
    ) * 10;
  const first = Date.parse(rows[0].timestamp);
  const last = Date.parse(rows.at(-1).timestamp);
  const x = (timestamp) =>
    55 + ((Date.parse(timestamp) - first) / Math.max(1, last - first)) * 680;
  const y = (value) => 215 - ((value - low) / (high - low)) * 185;
  for (let step = 0; step <= 4; step++) {
    const value = low + ((high - low) * step) / 4;
    svgElement("line", {
      x1: 55,
      x2: 735,
      y1: y(value),
      y2: y(value),
      stroke: "#e8eeeb",
    });
    svgElement(
      "text",
      {
        x: 43,
        y: y(value) + 4,
        "text-anchor": "end",
        fill: "#637578",
        "font-size": 11,
      },
      String(Math.round(value)),
    );
  }
  for (const index of [
    ...new Set([0, Math.floor(rows.length / 2), rows.length - 1]),
  ]) {
    svgElement(
      "text",
      {
        x: x(rows[index].timestamp),
        y: 244,
        "text-anchor": "middle",
        fill: "#637578",
        "font-size": 11,
      },
      rows[index].timestamp.slice(11, 16),
    );
  }
  if (sensor === "temperature") {
    svgElement("line", {
      x1: 55,
      x2: 735,
      y1: y(data.threshold),
      y2: y(data.threshold),
      stroke: "#c68d43",
      "stroke-dasharray": "5 5",
    });
  }
  // Start a new line across missing samples instead of visually inventing data.
  const path = rows
    .map((row, index) => {
      const gap =
        index === 0 ||
        Date.parse(row.timestamp) - Date.parse(rows[index - 1].timestamp) !==
          60000;
      return `${gap ? "M" : "L"}${x(row.timestamp)},${y(row.value)}`;
    })
    .join(" ");
  svgElement("path", {
    d: path,
    fill: "none",
    stroke: "#197666",
    "stroke-width": 2.5,
    "stroke-linejoin": "round",
  });
  for (const row of rows) {
    const dot = svgElement("circle", {
      cx: x(row.timestamp),
      cy: y(row.value),
      r: 4,
      fill: "transparent",
    });
    const title = document.createElementNS(svgNS, "title");
    title.textContent = `${row.timestamp.slice(11, 16)} UTC · ${row.value} ${sensor === "temperature" ? "°C" : "rpm"}`;
    dot.append(title);
  }
  if (selected !== null) {
    const alert = data.alerts[selected];
    const row = rows.find((row) => row.timestamp === alert.timestamp);
    if (row)
      svgElement("circle", {
        cx: x(row.timestamp),
        cy: y(row.value),
        r: 5,
        fill: "#c68d43",
        stroke: "white",
        "stroke-width": 2,
      });
  }
}

function selectAlert(index) {
  if (selected !== index) clearInvestigation();
  selected = index;
  alertButtons.forEach((button) => {
    const active = Number(button.dataset.alert) === selected;
    button.classList.toggle("selected", active);
    button.setAttribute("aria-pressed", String(active));
  });
  if (selected !== null) {
    const alert = data.alerts[selected];
    selection.textContent = `M-01 · ${alert.timestamp.slice(11, 16)} UTC · ${alert.value} °C, above threshold by ${alert.excess} °C.`;
  }
  drawChart();
}

alertButtons.forEach((button) =>
  button.addEventListener("click", () =>
    selectAlert(Number(button.dataset.alert)),
  ),
);
sensorButtons.forEach((button) =>
  button.addEventListener("click", () => {
    sensor = button.dataset.sensor;
    sensorButtons.forEach((tab) => {
      tab.classList.toggle("active", tab === button);
      tab.setAttribute("aria-pressed", String(tab === button));
    });
    drawChart();
  }),
);

search.addEventListener("submit", async (event) => {
  event.preventDefault();
  searchButton.disabled = true;
  searchStatus.textContent = "Searching…";
  results.replaceChildren();
  try {
    const response = await fetch(
      `/api/documents?q=${encodeURIComponent(query.value)}`,
    );
    if (!response.ok) throw new Error("Search failed");
    const documents = await response.json();
    searchStatus.textContent = documents.length
      ? `${documents.length} sections found · text search`
      : "No results. Try a word from the documents, such as temperature.";
    renderDocuments(documents, true);
  } catch {
    searchStatus.textContent =
      "Search unavailable. Check the local server and try again.";
  } finally {
    searchButton.disabled = false;
  }
});
renderDocuments(data.documents);
setInvestigating(false);
selectAlert(selected);

investigateButton.addEventListener("click", async () => {
  if (selected === null) return;
  clearInvestigation();
  setInvestigating(true);
  report.innerHTML =
    '<div class="generation-notice" role="status"><span class="loading-spinner" aria-hidden="true"></span><div><strong>Preparing your report</strong><p>Reviewing measurements and documents. Please wait.</p></div></div>';
  status.textContent =
    "Investigation in progress… the model is reviewing evidence.";
  try {
    const response = await fetch("/api/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scenario: data.scenario,
        alert_id: data.alerts[selected].id,
        context: context.value,
      }),
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.error || "Investigation unavailable.");
    report.innerHTML = result.report_html;
    status.textContent = `${result.model} · ${result.calls} requests · ${result.tokens} tokens · ${result.seconds} s. Hypotheses require verification.`;
    trace.textContent = JSON.stringify(result.trace, null, 2);
    tracePanel.hidden = false;
  } catch (error) {
    report.textContent = "";
    status.textContent =
      error instanceof SyntaxError || error instanceof TypeError
        ? "Connection interrupted. Check the server and try again."
        : error.message;
  } finally {
    setInvestigating(false);
  }
});
// Follow report citations to the exact evidence snapshot, including collapsed sources.
report.addEventListener("click", (event) => {
  const link = event.target.closest('a[href^="#evidence-"]');
  if (!link || !/^#evidence-\d+$/.test(link.getAttribute("href"))) return;
  const source = report.querySelector(link.getAttribute("href"));
  if (!source) return;
  event.preventDefault();
  source.open = true;
  source.scrollIntoView({ block: "center" });
  source.querySelector("summary").focus({ preventScroll: true });
});
