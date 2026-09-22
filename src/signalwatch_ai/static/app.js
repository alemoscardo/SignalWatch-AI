const data = JSON.parse(document.querySelector("#demo-data").textContent);
let sensor = "temperature";
let highlighted = null;
let reportScenario = data.scenario;
let investigating = false;
let selected = null;
let providerConfigured = Boolean(data.provider?.configured);
let providerModel = data.provider?.model || "openrouter/free";
let continueAfterProviderSave = false;
const sensors = {
  temperature: { label: "Temperature", unit: "°C" },
  speed: { label: "Speed", unit: "rpm" },
};

function formatUtc(timestamp) {
  return `${timestamp.slice(0, 16).replace("T", " ")} UTC`;
}

function describeAlert(alert, label = "M-01") {
  return `${label} · ${formatUtc(alert.timestamp)} · ${alert.value} °C, above threshold by ${alert.excess} °C.`;
}

function formatSavedDate(timestamp) {
  return new Date(timestamp).toLocaleString("en-GB");
}

const chart = document.querySelector("#chart");
const investigationPanel = document.querySelector(".investigation");
const closeInvestigation = document.querySelector("#close-investigation");
const chartAlerts = document.querySelector("#chart-alerts");
for (const [index, alert] of data.alerts.entries()) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = describeAlert(alert, "Temperature alert");
  button.addEventListener("click", () => selectAlert(index));
  chartAlerts.append(button);
}
closeInvestigation.addEventListener("click", () => {
  if (investigating) return;
  selectAlert(null);
  chart.focus();
});
const sensorButtons = document.querySelectorAll(".chart-tabs [data-sensor]");
const selection = document.querySelector("#selection");
const investigateButton = document.querySelector("#investigate");
const context = document.querySelector("#context");
const report = document.querySelector("#report");
const status = document.querySelector("#ai-status");
const trace = document.querySelector("#trace");
const tracePanel = document.querySelector("#trace-panel");
const ready = !investigateButton.disabled;
const providerSettings = document.querySelector("#provider-settings");
const providerDialog = document.querySelector("#provider-dialog");
const providerForm = document.querySelector("#provider-form");
const providerClose = document.querySelector("#provider-close");
const providerCancel = document.querySelector("#provider-cancel");
const providerForget = document.querySelector("#forget-provider");
const providerSubmit = document.querySelector("#provider-submit");
const providerKey = document.querySelector("#provider-key");
const providerModelInput = document.querySelector("#provider-model");
const providerDialogError = document.querySelector("#provider-dialog-error");
const historyList = document.querySelector("#history-list");
const historyStatus = document.querySelector("#history-status");
const chartSelection = document.querySelector("#chart-selection");
const search = document.querySelector("#search");
const searchButton = search.querySelector("button");
const query = document.querySelector("#query");
const searchStatus = document.querySelector("#search-status");
const results = document.querySelector("#results");

function updateProviderStatus(message = null) {
  if (message) {
    status.textContent = message;
    return;
  }
  status.textContent = providerConfigured
    ? `OpenRouter · ${providerModel} · session ready`
    : "AI not connected · add an OpenRouter key for this session";
  providerSettings.textContent = providerConfigured
    ? "Session settings"
    : "Connect OpenRouter";
}

function clearInvestigation() {
  highlighted = null;
  report.replaceChildren();
  trace.replaceChildren();
  tracePanel.hidden = true;
  tracePanel.open = false;
  updateProviderStatus();
}

function setInvestigating(active) {
  investigateButton.disabled = active || !ready || selected === null;
  investigating = active;
  historyList
    .querySelectorAll("button")
    .forEach((button) => (button.disabled = active));
  report.setAttribute("aria-busy", String(active));
  closeInvestigation.disabled = active;
  providerSettings.disabled = active;
  chartAlerts
    .querySelectorAll("button")
    .forEach((button) => (button.disabled = active));
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
    reference.textContent = `${doc.document} · ${doc.equipment || "historical"} · revision ${doc.revision || "unknown"}`;
    details.append(summary, text, reference);
    results.append(details);
  }
}

let chartRevision = 0;
const chartConfig = {
  responsive: true,
  displaylogo: false,
  displayModeBar: true,
  modeBarButtons: [["zoom2d", "pan2d", "resetScale2d"]],
  scrollZoom: false,
};

function drawChart(reset = false) {
  if (reset) chartRevision++;
  const rows = data[sensor];
  const { label, unit } = sensors[sensor];
  const points = [];
  // Explicit nulls prevent Plotly from joining samples across missing minutes.
  rows.forEach((row, index) => {
    if (
      index &&
      Date.parse(row.timestamp) - Date.parse(rows[index - 1].timestamp) !==
        60000
    )
      points.push(null);
    points.push(row);
  });
  const timestamp = (row) => row.timestamp.slice(0, 19);
  const hovertemplate = `%{x|%Y-%m-%d %H:%M} UTC · %{y} ${unit}<extra></extra>`;
  const traces = [
    {
      type: "scatter",
      mode: "lines",
      name: "Measurements",
      x: points.map((row) => (row ? timestamp(row) : null)),
      y: points.map((row) => row?.value ?? null),
      customdata: points,
      connectgaps: false,
      line: { color: "#197666", width: 2.5 },
      hovertemplate,
    },
  ];
  const alerts = data.alerts.flatMap((alert, alertIndex) => {
    const row = rows.find((row) => row.timestamp === alert.timestamp);
    return row ? [{ ...row, alertIndex }] : [];
  });
  traces.push({
    type: "scatter",
    mode: "markers",
    name: "Temperature alerts",
    x: alerts.map(timestamp),
    y: alerts.map((row) => row.value),
    customdata: alerts,
    marker: {
      color: alerts.map((row) =>
        row.alertIndex === selected ? "#a96518" : "#edc794",
      ),
      size: alerts.map((row) => (row.alertIndex === selected ? 14 : 10)),
      line: { color: "white", width: 2 },
    },
    hovertemplate: `Temperature alert · %{x|%Y-%m-%d %H:%M} UTC<br>${label}: %{y} ${unit}<extra>Click to select alert</extra>`,
  });
  const point =
    highlighted?.sensor === sensor
      ? rows.find(
          (row) =>
            row.timestamp === highlighted.timestamp &&
            row.value === Number(highlighted.value),
        )
      : null;
  traces.push({
    type: "scatter",
    mode: "markers",
    name: "Selected measurement",
    x: point ? [timestamp(point)] : [],
    y: point ? [point.value] : [],
    customdata: point ? [point] : [],
    marker: {
      color: "#136e62",
      size: 16,
      symbol: "circle-open",
      line: { width: 3 },
    },
    hovertemplate,
  });
  chartSelection.textContent = point
    ? `${label} · ${formatUtc(point.timestamp)} · ${point.value} ${unit}`
    : highlighted?.sensor === sensor
      ? "This saved measurement is not present in the current graph. See its source snapshot below."
      : "Select an amber alert to investigate. Drag to pan; use Zoom for a closer view.";
  return Plotly.react(
    chart,
    traces,
    {
      uirevision: `${sensor}-${chartRevision}`,
      showlegend: false,
      margin: { l: 48, r: 15, t: 32, b: 40 },
      font: {
        family: 'Inter, "Segoe UI", sans-serif',
        color: "#637578",
        size: 11,
      },
      paper_bgcolor: "white",
      plot_bgcolor: "white",
      hovermode: "closest",
      dragmode: "pan",
      xaxis: {
        type: "date",
        tickformat: "%H:%M<br>%d %b",
        showgrid: false,
        zeroline: false,
        autorange: true,
      },
      yaxis: { gridcolor: "#e8eeeb", zeroline: false, autorange: true },
      shapes:
        sensor === "temperature"
          ? [
              {
                type: "line",
                xref: "paper",
                x0: 0,
                x1: 1,
                y0: data.threshold,
                y1: data.threshold,
                line: { color: "#c68d43", dash: "dash", width: 1 },
              },
            ]
          : [],
      annotations: rows.length
        ? []
        : [
            {
              text: "No measurements available",
              showarrow: false,
              xref: "paper",
              yref: "paper",
              x: 0.5,
              y: 0.5,
            },
          ],
    },
    chartConfig,
  );
}

chart.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  const rows = data[sensor];
  if (!rows.length) return;
  event.preventDefault();
  const current =
    highlighted?.sensor === sensor
      ? rows.findIndex((row) => row.timestamp === highlighted.timestamp)
      : -1;
  const index = Math.max(
    0,
    Math.min(rows.length - 1, current + (event.key === "ArrowRight" ? 1 : -1)),
  );
  highlighted = rows[index];
  drawChart();
});

function selectAlert(index, saved = null) {
  if (index < 0) index = null;
  if (selected !== index || saved || index === null) clearInvestigation();
  selected = index;
  investigationPanel.hidden = selected === null && !saved;
  investigateButton.disabled = investigating || !ready || selected === null;
  const alert = saved?.alert || data.alerts[selected];
  selection.textContent = alert
    ? describeAlert(alert, saved ? "Saved alert" : "M-01")
    : "No alert selected. Choose an available alert to investigate.";
  if (saved) {
    context.value = saved.context;
    showReport(saved);
  }
  drawChart();
  if (!investigationPanel.hidden)
    investigationPanel.scrollIntoView({ block: "nearest" });
}

function selectSensor(value, reset = false) {
  sensor = value;
  sensorButtons.forEach((tab) => {
    const active = tab.dataset.sensor === sensor;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-pressed", String(active));
  });
  drawChart(reset);
}
sensorButtons.forEach((button) =>
  button.addEventListener("click", () => selectSensor(button.dataset.sensor)),
);

function showReport(result) {
  reportScenario = result.scenario || data.scenario;
  report.innerHTML = result.report_html;
  status.textContent = `${result.model} · ${result.calls} requests · ${result.tokens ?? "unknown"} tokens · ${result.seconds} s. ${result.status === "insufficient_evidence" ? "Insufficient evidence." : "Hypotheses require verification."}`;
  if (result.created_at)
    status.textContent = `Saved ${formatSavedDate(result.created_at)} · ${status.textContent}`;
  trace.textContent = JSON.stringify(result.trace, null, 2);
  tracePanel.hidden = false;
}

async function loadHistory() {
  try {
    const response = await fetch("/api/investigations");
    if (!response.ok) throw new Error();
    const items = await response.json();
    historyList.replaceChildren();
    historyStatus.textContent = items.length
      ? "Saved on this computer"
      : "No saved investigations yet.";
    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.disabled = investigating;
      button.textContent = `${formatSavedDate(item.created_at)} · Alert ${formatUtc(item.alert_time)}`;
      button.addEventListener("click", async () => {
        if (investigating) return;
        setInvestigating(true);
        try {
          const response = await fetch(`/api/investigations/${item.id}`);
          if (!response.ok) throw new Error();
          const saved = await response.json();
          selectAlert(
            saved.scenario === data.scenario
              ? data.alerts.findIndex((alert) => alert.id === saved.alert.id)
              : -1,
            saved,
          );
          report.scrollIntoView({ block: "start" });
        } catch {
          historyStatus.textContent =
            "Could not open this investigation. Try again.";
        } finally {
          setInvestigating(false);
        }
      });
      historyList.append(button);
    }
  } catch {
    historyStatus.textContent = "History unavailable. Try reloading the page.";
  }
}

function closeProviderDialog() {
  providerDialog.close();
  providerKey.value = "";
  providerDialogError.textContent = "";
  continueAfterProviderSave = false;
}

function openProviderDialog({ continueInvestigation = false } = {}) {
  if (investigating) return;
  continueAfterProviderSave = continueInvestigation;
  providerDialogError.textContent = "";
  providerKey.value = "";
  providerModelInput.value = providerModel;
  providerForget.hidden = !providerConfigured;
  providerDialog.showModal();
  providerKey.focus();
}

async function forgetProviderSession() {
  providerForget.disabled = true;
  try {
    const response = await fetch("/api/provider/session", {
      method: "DELETE",
      headers: { Accept: "application/json" },
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.error || "Could not forget the session key.");
    providerConfigured = Boolean(result.configured);
    providerModel = result.model || providerModel;
    closeProviderDialog();
    updateProviderStatus();
  } catch (error) {
    providerDialogError.textContent = error.message;
  } finally {
    providerForget.disabled = false;
  }
}

async function saveProviderSession(event) {
  event.preventDefault();
  const apiKey = providerKey.value.trim();
  const model = providerModelInput.value.trim();
  if (!apiKey || !model) {
    providerDialogError.textContent = "Enter both an API key and a model identifier.";
    return;
  }
  providerSubmit.disabled = true;
  providerCancel.disabled = true;
  providerForget.disabled = true;
  providerDialogError.textContent = "";
  try {
    const response = await fetch("/api/provider/session", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ api_key: apiKey, model }),
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.error || "Could not configure OpenRouter.");
    providerConfigured = Boolean(result.configured);
    providerModel = result.model || model;
    const shouldContinue = continueAfterProviderSave;
    closeProviderDialog();
    updateProviderStatus();
    if (shouldContinue) await runInvestigation();
  } catch (error) {
    providerDialogError.textContent = error.message;
  } finally {
    providerSubmit.disabled = false;
    providerCancel.disabled = false;
    providerForget.disabled = false;
  }
}

providerSettings.addEventListener("click", () => openProviderDialog());
providerClose.addEventListener("click", closeProviderDialog);
providerCancel.addEventListener("click", closeProviderDialog);
providerForget.addEventListener("click", forgetProviderSession);
providerForm.addEventListener("submit", saveProviderSession);
providerDialog.addEventListener("close", () => {
  providerKey.value = "";
  providerDialogError.textContent = "";
  continueAfterProviderSave = false;
});

search.addEventListener("submit", async (event) => {
  event.preventDefault();
  searchButton.disabled = true;
  searchStatus.textContent = "Searching…";
  results.replaceChildren();
  try {
    const response = await fetch(
      `/api/documents?q=${encodeURIComponent(query.value)}`,
    );
    const documents = await response.json();
    if (!response.ok) throw new Error(documents.error || "Search unavailable. Try again later.");
    searchStatus.textContent = documents.length
      ? `${documents.length} sections found · semantic search`
      : "No applicable evidence found. Try a more specific question.";
    renderDocuments(documents, true);
  } catch (error) {
    searchStatus.textContent = error instanceof TypeError
      ? "Search unavailable. Check the local server and try again."
      : error.message;
  } finally {
    searchButton.disabled = false;
  }
});
renderDocuments(data.documents);
setInvestigating(false);
selectAlert(selected);
chart.on("plotly_click", (event) => {
  const row = event.points[0]?.customdata;
  if (!row) return;
  const alertIndex = data.alerts.findIndex(
    (alert) => alert.timestamp === row.timestamp,
  );
  if (alertIndex !== -1) {
    if (!investigating) selectAlert(alertIndex);
    return;
  }
  highlighted = row;
  drawChart();
});
loadHistory();

async function runInvestigation() {
  if (selected === null || investigating) return;
  clearInvestigation();
  drawChart();
  setInvestigating(true);
  report.innerHTML =
    '<div class="generation-notice" role="status"><span class="loading-spinner" aria-hidden="true"></span><div><strong>Investigation in progress</strong><p id="progress-message">Connecting…</p></div></div>';
  status.textContent = "";
  try {
    const response = await fetch("/api/investigate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/x-ndjson",
      },
      body: JSON.stringify({
        scenario: data.scenario,
        alert_id: data.alerts[selected].id,
        context: context.value,
      }),
    });
    if (!response.ok) {
      const failure = await response.json();
      throw new Error(failure.error || "Investigation unavailable.");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completed = false;
    const handleLine = (line) => {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      if (event.type === "progress")
        document.querySelector("#progress-message").textContent = event.message;
      if (event.type === "error") throw new Error(event.message);
      if (event.type === "result") {
        showReport(event.result);
        completed = true;
      }
    };
    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        lines.forEach(handleLine);
        if (done) break;
      }
      handleLine(buffer);
      if (!completed)
        throw new Error(
          "Connection ended before the investigation completed. Check Previous investigations before retrying.",
        );
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
    await loadHistory();
  } catch (error) {
    report.textContent = "";
    status.textContent =
      error instanceof SyntaxError || error instanceof TypeError
        ? "Connection interrupted. Check the server and try again."
        : error.message;
  } finally {
    setInvestigating(false);
  }
}
investigateButton.addEventListener("click", () => {
  if (selected === null || investigating) return;
  if (!providerConfigured) {
    openProviderDialog({ continueInvestigation: true });
    return;
  }
  runInvestigation();
});
// Follow report citations to the exact evidence snapshot, including collapsed sources.
report.addEventListener("click", (event) => {
  const link = event.target.closest('a[href^="#evidence-"]');
  if (!link || !/^#evidence-\d+$/.test(link.getAttribute("href"))) return;
  const source = report.querySelector(link.getAttribute("href"));
  if (!source) return;
  event.preventDefault();
  source.open = true;
  if (link.dataset.sensor && reportScenario === data.scenario) {
    highlighted = {
      sensor: link.dataset.sensor,
      timestamp: link.dataset.timestamp,
      value: Number(link.dataset.value),
    };
    selectSensor(highlighted.sensor, true);
    chart.scrollIntoView({ block: "center" });
    chart.focus({ preventScroll: true });
  } else {
    source.scrollIntoView({ block: "center" });
    source.querySelector("summary").focus({ preventScroll: true });
  }
});
