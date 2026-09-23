const data = JSON.parse(document.querySelector("#demo-data").textContent);
let sensor = "temperature";
let highlighted = null;
let activeContext = null;
let activeThreadId = null;
let currentThreads = [];
let streaming = false;
let stopRequested = false;
let controller = null;
let chartRevision = 0;
let providerConfigured = Boolean(data.provider?.configured);
let providerModel = data.provider?.model || "openrouter/free";
const sensors = {
  temperature: { label: "Temperature", unit: "°C" },
  speed: { label: "Speed", unit: "rpm" },
};

const chart = document.querySelector("#chart");
const threadList = document.querySelector("#thread-list");
const alertList = document.querySelector("#alert-list");
const datasetSelect = document.querySelector("#dataset-select");
const datasetTitle = document.querySelector("#dataset-title");
const datasetRange = document.querySelector("#dataset-range");
const chartNote = document.querySelector("#chart-note");
const chartSelection = document.querySelector("#chart-selection");
const chartAlerts = document.querySelector("#chart-alerts");
const chatTitle = document.querySelector("#chat-title");
const activeContextLabel = document.querySelector("#active-context");
const chatMessages = document.querySelector("#chat-messages");
const chatForm = document.querySelector("#chat-form");
const messageInput = document.querySelector("#message");
const sendButton = document.querySelector("#send-message");
const stopButton = document.querySelector("#stop-chat");
const conversationStatus = document.querySelector("#conversation-status");
const contextStatus = document.querySelector("#context-status");
const sensorButtons = document.querySelectorAll(".chart-tabs [data-sensor]");
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
const legacyDialog = document.querySelector("#legacy-dialog");
const legacyReport = document.querySelector("#legacy-report");
const legacyMeta = document.querySelector("#legacy-meta");
const legacyTrace = document.querySelector("#legacy-trace");
const search = document.querySelector("#search");
const searchButton = search.querySelector("button");
const query = document.querySelector("#query");
const searchStatus = document.querySelector("#search-status");
const results = document.querySelector("#results");

function formatUtc(timestamp) {
  return `${timestamp.slice(0, 16).replace("T", " ")} UTC`;
}

function formatSavedDate(timestamp) {
  return new Date(timestamp).toLocaleString("en-GB");
}

function alertReference(dataset, alert) {
  return alert.reference || `a:${dataset}@${alert.timestamp}`;
}

function describeAlert(alert) {
  return `${formatUtc(alert.timestamp)} · ${alert.value} °C · +${alert.excess} °C`;
}

function updateProviderStatus(message = null) {
  const status = document.querySelector("#ai-status");
  status.textContent = message || (providerConfigured
    ? `OpenRouter · ${providerModel} · session ready`
    : "AI not connected · add an OpenRouter key for this session");
  providerSettings.textContent = providerConfigured ? "Session settings" : "Connect OpenRouter";
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

const chartConfig = {
  responsive: true,
  displaylogo: false,
  displayModeBar: true,
  modeBarButtons: [["zoom2d", "pan2d", "resetScale2d"]],
  scrollZoom: false,
};

function drawChart(reset = false) {
  if (reset) chartRevision++;
  const rows = data[sensor] || [];
  const { label, unit } = sensors[sensor];
  const points = [];
  rows.forEach((row, index) => {
    if (index && Date.parse(row.timestamp) - Date.parse(rows[index - 1].timestamp) !== 60000)
      points.push(null);
    points.push(row);
  });
  const timestamp = (row) => row.timestamp.slice(0, 19);
  const hovertemplate = `%{x|%Y-%m-%d %H:%M} UTC · %{y} ${unit}<extra></extra>`;
  const traces = [{
    type: "scatter", mode: "lines", name: "Measurements",
    x: points.map((row) => row ? timestamp(row) : null),
    y: points.map((row) => row?.value ?? null), customdata: points,
    connectgaps: false, line: { color: "#197666", width: 2.5 }, hovertemplate,
  }];
  const alerts = (data.alerts || []).flatMap((alert) => {
    const row = rows.find((measurement) => measurement.timestamp === alert.timestamp);
    return row ? [{ ...row, reference: alertReference(data.scenario, alert) }] : [];
  });
  traces.push({
    type: "scatter", mode: "markers", name: "Temperature alerts",
    x: alerts.map(timestamp), y: alerts.map((row) => row.value), customdata: alerts,
    marker: {
      color: alerts.map((row) => row.reference === activeContext?.alert?.reference ? "#a96518" : "#edc794"),
      size: alerts.map((row) => row.reference === activeContext?.alert?.reference ? 14 : 10),
      line: { color: "white", width: 2 },
    },
    hovertemplate: `Temperature alert · %{x|%Y-%m-%d %H:%M} UTC<br>${label}: %{y} ${unit}<extra>Click to select alert</extra>`,
  });
  const point = highlighted?.sensor === sensor
    ? rows.find((row) => row.timestamp === highlighted.timestamp && row.value === Number(highlighted.value))
    : null;
  traces.push({
    type: "scatter", mode: "markers", name: "Selected measurement",
    x: point ? [timestamp(point)] : [], y: point ? [point.value] : [], customdata: point ? [point] : [],
    marker: { color: "#136e62", size: 16, symbol: "circle-open", line: { width: 3 } }, hovertemplate,
  });
  chartSelection.textContent = point
    ? `${label} · ${formatUtc(point.timestamp)} · ${point.value} ${unit}`
    : highlighted?.sensor === sensor
      ? "This saved measurement is not present in the current graph."
      : "Select an amber alert to add its snapshot to the conversation.";
  return Plotly.react(chart, traces, {
    uirevision: `${data.scenario}-${sensor}-${chartRevision}`,
    showlegend: false, margin: { l: 48, r: 15, t: 32, b: 40 },
    font: { family: 'Inter, "Segoe UI", sans-serif', color: "#637578", size: 11 },
    paper_bgcolor: "white", plot_bgcolor: "white", hovermode: "closest", dragmode: "pan",
    xaxis: { type: "date", tickformat: "%H:%M<br>%d %b", showgrid: false, zeroline: false, autorange: true },
    yaxis: { gridcolor: "#e8eeeb", zeroline: false, autorange: true },
    shapes: sensor === "temperature" ? [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: data.threshold, y1: data.threshold, line: { color: "#c68d43", dash: "dash", width: 1 } }] : [],
    annotations: rows.length ? [] : [{ text: "No measurements available", showarrow: false, xref: "paper", yref: "paper", x: 0.5, y: 0.5 }],
  }, chartConfig);
}

function renderAlertList() {
  alertList.replaceChildren();
  chartAlerts.replaceChildren();
  const alerts = data.alerts || [];
  if (!alerts.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No temperature alerts in this dataset.";
    alertList.append(empty);
    return;
  }
  for (const alert of alerts) {
    const reference = alertReference(data.scenario, alert);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "alert-choice";
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(reference === activeContext?.alert?.reference));
    button.classList.toggle("active", reference === activeContext?.alert?.reference);
    const time = document.createElement("strong");
    time.textContent = formatUtc(alert.timestamp);
    const value = document.createElement("span");
    value.textContent = `${alert.value} °C · ${alert.excess} °C above threshold`;
    button.append(time, value);
    button.addEventListener("click", () => chooseAlert(alert));
    alertList.append(button);

    const accessible = document.createElement("button");
    accessible.type = "button";
    const equipment = (data.datasets || []).find((item) => item.id === data.scenario)?.equipment || "Equipment";
    accessible.textContent = `${equipment} · ${describeAlert(alert)}`;
    accessible.addEventListener("click", () => chooseAlert(alert));
    chartAlerts.append(accessible);
  }
}

function updateContextUI() {
  const alert = activeContext?.alert;
  if (alert) {
    const dataset = activeContext.dataset;
    const metadata = (data.datasets || []).find((item) => item.id === dataset);
    activeContextLabel.textContent = `${metadata?.label || dataset} · ${metadata?.equipment || alert.equipment} · ${formatUtc(alert.timestamp)}`;
    contextStatus.textContent = `Selected for the next message · ${alert.value} °C at ${formatUtc(alert.timestamp)}.`;
    document.querySelector("#clear-context").disabled = false;
  } else {
    activeContextLabel.textContent = "No alert selected · ask about any dataset";
    contextStatus.textContent = "Choose an alert to add its snapshot to the next message.";
    document.querySelector("#clear-context").disabled = true;
  }
  renderAlertList();
  return drawChart();
}

async function saveContext(context) {
  if (activeThreadId) {
    const body = context ? { dataset: context.dataset, alert_id: context.alert.id } : {};
    const response = await fetch(`/api/chats/${activeThreadId}/context`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not update alert context.");
  }
  activeContext = context;
  await updateContextUI();
}

async function chooseAlert(alert) {
  const reference = alertReference(data.scenario, alert);
  const context = {
    dataset: data.scenario,
    alert: {
      ...alert,
      dataset: data.scenario,
      equipment: data.equipment,
      reference,
      citation: `[ref:${reference}]`,
      source_type: "alert",
    },
  };
  try {
    await saveContext(context);
    contextStatus.textContent = `${alert.value} °C alert selected · context applies to your next message.`;
  } catch (error) {
    contextStatus.textContent = error.message;
  }
}

async function loadDataset(datasetId) {
  if (datasetId === data.scenario) return;
  chartSelection.textContent = "Loading telemetry…";
  try {
    const response = await fetch(`/api/telemetry/${encodeURIComponent(datasetId)}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not load telemetry.");
    Object.assign(data, result);
    highlighted = null;
    datasetTitle.textContent = `${result.label} · ${result.equipment}`;
    datasetRange.textContent = result.start && result.end
      ? `${formatUtc(result.start)} – ${formatUtc(result.end)}`
      : "No measurements available";
    chartNote.textContent = `Temperature threshold ${Number(data.threshold).toFixed(0)} °C · Click an amber marker to select its alert context`;
    renderAlertList();
    drawChart(true);
  } catch (error) {
    chartSelection.textContent = error.message;
  }
}

function renderThreadList() {
  threadList.replaceChildren();
  if (!currentThreads.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No saved chats yet.";
    threadList.append(empty);
    return;
  }
  for (const thread of currentThreads) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "thread-choice";
    button.classList.toggle("active", thread.id === activeThreadId);
    button.disabled = streaming;
    const title = document.createElement("strong");
    title.textContent = thread.title || "New chat";
    const meta = document.createElement("span");
    const context = thread.active_context;
    const last = thread.last_message || (context?.alert ? `${context.dataset} · ${formatUtc(context.alert.timestamp)}` : "No messages yet");
    meta.textContent = last.length > 74 ? `${last.slice(0, 71)}…` : last;
    button.append(title, meta);
    button.addEventListener("click", () => openThread(thread.id));
    threadList.append(button);
  }
}

async function refreshThreads() {
  const response = await fetch("/api/chats");
  if (!response.ok) throw new Error("Could not load saved chats.");
  currentThreads = await response.json();
  renderThreadList();
}

function welcomeMessage() {
  chatMessages.replaceChildren();
  const welcome = document.createElement("div");
  welcome.className = "welcome-card";
  welcome.innerHTML = "<strong>Ask SignalWatch</strong><p>Choose an alert for focused context, or ask a question across all telemetry datasets. Open Tool Calls to inspect the checks behind each answer.</p>";
  chatMessages.append(welcome);
}

function appendMessage(role, content = "") {
  const wrapper = document.createElement("article");
  wrapper.className = `chat-message chat-message--${role}`;
  const label = document.createElement("span");
  label.className = "chat-message__label";
  label.textContent = role === "user" ? "You" : role === "assistant" ? "SignalWatch" : "Agent";
  const body = document.createElement("div");
  body.className = "chat-message__body";
  if (role === "assistant") body.classList.add("assistant-message");
  if (content instanceof Node) body.append(content);
  else body.textContent = content;
  wrapper.append(label, body);
  chatMessages.append(wrapper);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return { wrapper, body };
}

function appendNotice(text, kind = "notice") {
  const notice = document.createElement("div");
  notice.className = `chat-notice chat-notice--${kind}`;
  notice.textContent = text;
  chatMessages.append(notice);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return notice;
}

function renderToolCard(event, live = false) {
  const card = document.createElement("details");
  card.className = "tool-card";
  card.open = true;
  const summary = document.createElement("summary");
  const name = document.createElement("strong");
  name.textContent = event.tool || "Read-only tool";
  const state = document.createElement("span");
  state.className = "tool-card__state";
  state.textContent = live ? "Running…" : `${Array.isArray(event.result) ? `${event.result.length} result${event.result.length === 1 ? "" : "s"}` : event.result?.error ? "Needs attention" : "Complete"}${event.seconds != null ? ` · ${event.seconds}s` : ""}`;
  summary.append(name, state);
  const args = document.createElement("pre");
  args.className = "tool-card__args";
  args.textContent = JSON.stringify(event.arguments || {}, null, 2);
  const output = document.createElement("pre");
  output.className = "tool-card__output";
  output.textContent = live ? "Waiting for tool result…" : JSON.stringify(event.result ?? {}, null, 2);
  card.append(summary, args, output);
  return { card, state, output };
}

function createToolCallsPanel(live = false) {
  const panel = document.createElement("details");
  panel.className = "tool-calls";
  const summary = document.createElement("summary");
  const label = document.createElement("strong");
  label.className = "tool-calls__label";
  label.textContent = "Tool Calls";
  const state = document.createElement("span");
  state.className = "tool-calls__state";
  if (live) state.textContent = "In progress";
  summary.append(label, state);
  const steps = document.createElement("div");
  steps.className = "tool-calls__steps";
  panel.append(summary, steps);

  function updateState(text) {
    state.textContent = text;
  }

  function appendTool(event, live = false) {
    const tool = renderToolCard(event, live);
    const wrapper = document.createElement("div");
    wrapper.className = "tool-message";
    wrapper.append(tool.card);
    steps.append(wrapper);
    updateState(`${steps.children.length} ${steps.children.length === 1 ? "step" : "steps"}${live ? " · in progress" : ""}`);
    return tool;
  }

  function finish() {
    if (!steps.children.length) {
      panel.remove();
      return;
    }
    updateState(`${steps.children.length} ${steps.children.length === 1 ? "step" : "steps"}`);
  }

  return { panel, steps, updateState, appendTool, finish };
}

function setThinkingIndicator(indicator, message, visible = true) {
  indicator.querySelector(".thinking-indicator__label").textContent = message;
  indicator.hidden = !visible;
}

function toolActivityLabel(tool) {
  const labels = {
    list_datasets: "Checking available datasets",
    list_alerts: "Checking alerts",
    read_measurements: "Reading telemetry",
    search_documents: "Searching technical guidance",
    open_saved_evidence: "Reviewing saved evidence",
  };
  return labels[tool] || "Checking the available evidence";
}

function appendResponseWarning(body, message) {
  const warning = document.createElement("details");
  warning.className = "response-warning";
  const summary = document.createElement("summary");
  summary.textContent = /citation|reference|evidence/i.test(message)
    ? "Citation warning"
    : "Response warning";
  const explanation = document.createElement("p");
  explanation.textContent = message;
  warning.append(summary, explanation);
  body.append(warning);
  return warning;
}

function renderTurn(turn, compactions) {
  const turnId = turn.id;
  for (const compaction of compactions) {
    if (!compaction._shown && compaction.through_turn_id < turnId) {
      compaction._shown = true;
      const details = document.createElement("details");
      details.className = "compaction-card";
      const summary = document.createElement("summary");
      summary.textContent = `Conversation memory updated · ${compaction.context_tokens_before} → ${compaction.context_tokens_after || "?"} estimated tokens`;
      const text = document.createElement("p");
      text.textContent = compaction.summary;
      details.append(summary, text);
      chatMessages.append(details);
    }
  }
  appendMessage("user", turn.user_message);
  if (turn.trace?.length) {
    const toolCalls = createToolCallsPanel();
    for (const event of turn.trace) toolCalls.appendTool(event);
    chatMessages.append(toolCalls.panel);
  }
  let assistantMessage = null;
  const answerHtml = turn.assistant_html || turn.partial_html;
  if (answerHtml || turn.partial_message) {
    assistantMessage = appendMessage("assistant");
    if (answerHtml) assistantMessage.body.innerHTML = answerHtml;
    else assistantMessage.body.textContent = turn.partial_message;
  }
  if (turn.status === "interrupted") appendNotice("Generation stopped. The partial response is saved with this chat.", "muted");
  else if (turn.status === "error") {
    if (assistantMessage) appendResponseWarning(assistantMessage.body, turn.error || "The agent could not complete this turn.");
    else appendNotice(turn.error || "The agent could not complete this turn.", "error");
  }
  else if (turn.status === "running") appendNotice("This turn is still running in another window.", "muted");
  if (turn.metrics) {
    const metrics = document.createElement("p");
    metrics.className = "turn-metrics";
    const tokens = turn.metrics.tokens == null ? "token usage unavailable" : `${turn.metrics.tokens} tokens`;
    metrics.textContent = `${turn.metrics.models?.join(", ") || providerModel} · ${turn.metrics.calls || 0} requests · ${tokens} · ${turn.metrics.seconds ?? "?"}s`;
    chatMessages.append(metrics);
  }
}

function renderChat(chat) {
  chatTitle.textContent = chat.thread.title || "New chat";
  activeContext = chat.thread.active_context;
  updateContextUI();
  chatMessages.replaceChildren();
  const compactions = (chat.compactions || []).map((item) => ({ ...item, _shown: false }));
  if (!chat.turns.length) welcomeMessage();
  else for (const turn of chat.turns) renderTurn(turn, compactions);
  for (const compaction of compactions) {
    if (compaction._shown) continue;
    const details = document.createElement("details");
    details.className = "compaction-card";
    const summary = document.createElement("summary");
    summary.textContent = `Conversation memory updated · ${compaction.context_tokens_before} → ${compaction.context_tokens_after || "?"} estimated tokens`;
    const text = document.createElement("p");
    text.textContent = compaction.summary;
    details.append(summary, text);
    chatMessages.append(details);
  }
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function openThread(threadId) {
  if (streaming) return;
  try {
    const response = await fetch(`/api/chats/${threadId}`);
    const chat = await response.json();
    if (!response.ok) throw new Error(chat.error || "Could not open this chat.");
    activeThreadId = threadId;
    if (chat.thread.active_context?.dataset && chat.thread.active_context.dataset !== data.scenario) {
      datasetSelect.value = chat.thread.active_context.dataset;
      await loadDataset(chat.thread.active_context.dataset);
    }
    renderChat(chat);
    await refreshThreads();
    conversationStatus.textContent = "Saved conversation";
  } catch (error) {
    conversationStatus.textContent = error.message;
  }
}

async function createThread() {
  const response = await fetch("/api/chats", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
  });
  const thread = await response.json();
  if (!response.ok) throw new Error(thread.error || "Could not create a chat.");
  activeThreadId = thread.id;
  if (activeContext) {
    const contextResponse = await fetch(`/api/chats/${thread.id}/context`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataset: activeContext.dataset, alert_id: activeContext.alert.id }),
    });
    if (!contextResponse.ok) throw new Error("Could not set the alert context for this chat.");
  }
  await refreshThreads();
  return thread.id;
}

function setStreaming(value) {
  streaming = value;
  messageInput.disabled = value;
  sendButton.disabled = value;
  stopButton.hidden = !value;
  stopButton.disabled = value;
  document.querySelector("#new-chat").disabled = value;
  renderThreadList();
}

async function handleChatEvent(event, state) {
  if (event.type === "request_started") {
    stopButton.disabled = false;
    conversationStatus.textContent = `Thinking · request ${event.request}`;
    setThinkingIndicator(
      state.thinking,
      event.request > 1 ? "Reviewing the evidence" : "SignalWatch is thinking",
    );
  } else if (event.type === "text_delta") {
    setThinkingIndicator(state.thinking, "", false);
    state.provisional.textContent += event.text;
    chatMessages.scrollTop = chatMessages.scrollHeight;
  } else if (event.type === "clear_provisional") {
    state.provisional.textContent = "";
    setThinkingIndicator(state.thinking, "Reviewing the evidence");
  } else if (event.type === "metrics") {
    const tokenLabel = event.tokens == null ? "token usage unavailable" : `${event.tokens} tokens`;
    conversationStatus.textContent = `${event.models?.join(", ") || providerModel} · ${event.calls} requests · ${tokenLabel}`;
  } else if (event.type === "tool_started") {
    conversationStatus.textContent = `Using ${event.tool}…`;
    setThinkingIndicator(state.thinking, toolActivityLabel(event.tool));
    const tool = state.toolCalls.appendTool({ ...event, result: null }, true);
    state.tools.set(event.call_id, tool);
  } else if (event.type === "tool_finished") {
    const tool = state.tools.get(event.tool_call_id);
    if (tool) {
      tool.state.textContent = `${Array.isArray(event.result) ? `${event.result.length} result${event.result.length === 1 ? "" : "s"}` : event.result?.error ? "Needs attention" : "Complete"} · ${event.seconds}s`;
      tool.output.textContent = JSON.stringify(event.result ?? {}, null, 2);
      state.toolCalls.updateState("Reviewing the results");
      setThinkingIndicator(state.thinking, "Reviewing the results");
    }
    chatMessages.scrollTop = chatMessages.scrollHeight;
  } else if (event.type === "context_compacted") {
    appendNotice(event.reason, "muted");
  } else if (event.type === "compaction") {
    const details = document.createElement("details");
    details.className = "compaction-card";
    const summary = document.createElement("summary");
    summary.textContent = `Conversation memory updated · ${event.tokens_before} → ${event.tokens_after} estimated tokens`;
    const text = document.createElement("p");
    text.textContent = event.summary;
    details.append(summary, text);
    chatMessages.insertBefore(details, state.pending.wrapper);
  } else if (event.type === "done") {
    state.thinking.remove();
    state.toolCalls.finish();
    state.pending.body.innerHTML = event.assistant_html;
    state.provisional.remove();
    state.pending.wrapper.classList.add("chat-message--complete");
    const metrics = event.metrics || {};
    const tokens = metrics.tokens == null ? "token usage unavailable" : `${metrics.tokens} tokens`;
    conversationStatus.textContent = `${metrics.models?.join(", ") || providerModel} · ${metrics.calls || 0} requests · ${tokens} · ${metrics.seconds ?? "?"}s`;
    state.completed = true;
  } else if (event.type === "interrupted") {
    state.thinking.remove();
    state.toolCalls.finish();
    state.provisional.remove();
    state.pending.body.textContent = event.partial || "Generation stopped.";
    state.pending.wrapper.classList.add("chat-message--interrupted");
    appendNotice("Generation stopped. The partial response is saved with this chat.", "muted");
    state.completed = true;
  } else if (event.type === "error") {
    state.provisional.remove();
    state.thinking.remove();
    state.toolCalls.finish();
    if (event.partial_html) {
      state.pending.body.innerHTML = event.partial_html;
      appendResponseWarning(
        state.pending.body,
        event.message || "The agent could not complete this response cleanly.",
      );
      state.pending.wrapper.classList.add("chat-message--complete");
      conversationStatus.textContent = "Response saved with a warning";
    } else {
      if (event.message) appendNotice(event.message, "error");
      state.pending.wrapper.remove();
    }
    state.completed = true;
  }
}

async function readNdjson(response, state) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  async function handle(line) {
    if (!line.trim()) return;
    await handleChatEvent(JSON.parse(line), state);
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) await handle(line);
      if (done) break;
    }
    await handle(buffer);
  } finally {
    reader.releaseLock();
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message || streaming) return;
  if (!providerConfigured) {
    providerDialog.showModal();
    providerKey.focus();
    conversationStatus.textContent = "Connect OpenRouter, then press Send again.";
    return;
  }
  sendButton.disabled = true;
  try {
    if (!activeThreadId) await createThread();
  } catch (error) {
    conversationStatus.textContent = error.message;
    sendButton.disabled = false;
    return;
  }
  const user = appendMessage("user", message);
  messageInput.value = "";
  const toolCalls = createToolCallsPanel(true);
  chatMessages.append(toolCalls.panel);
  const pending = appendMessage("assistant");
  pending.body.classList.add("assistant-message--streaming");
  const thinking = document.createElement("span");
  thinking.className = "thinking-indicator";
  thinking.setAttribute("role", "status");
  const thinkingLabel = document.createElement("span");
  thinkingLabel.className = "thinking-indicator__label";
  thinkingLabel.textContent = "Connecting to SignalWatch";
  const dots = document.createElement("span");
  dots.className = "thinking-indicator__dots";
  dots.setAttribute("aria-hidden", "true");
  for (let index = 0; index < 3; index += 1) dots.append(document.createElement("i"));
  thinking.append(thinkingLabel, dots);
  pending.body.append(thinking);
  const provisional = document.createElement("span");
  provisional.className = "provisional-text";
  pending.body.append(provisional);
  const state = { pending, provisional, thinking, toolCalls, tools: new Map(), completed: false };
  setStreaming(true);
  stopRequested = false;
  controller = new AbortController();
  conversationStatus.textContent = "Connecting…";
  try {
    const response = await fetch(`/api/chats/${activeThreadId}/turns`, {
      method: "POST", signal: controller.signal,
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify({ request_id: crypto.randomUUID(), message }),
    });
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      throw new Error(failure.error || "The agent could not start this turn.");
    }
    await readNdjson(response, state);
    if (!state.completed) {
      state.toolCalls.finish();
      state.provisional.remove();
      state.pending.wrapper.remove();
      appendNotice("Connection ended before SignalWatch completed the response. Reload the chat to check the saved turn.", "error");
    }
  } catch (error) {
    state.toolCalls.finish();
    state.provisional.remove();
    state.pending.wrapper.remove();
    if (stopRequested) appendNotice("Stopping generation… saved progress will appear when the chat reloads.", "muted");
    else appendNotice(error instanceof TypeError ? "Connection interrupted. Check the local server and try again." : error.message, "error");
  } finally {
    controller = null;
    setStreaming(false);
    try {
      const response = await fetch(`/api/chats/${activeThreadId}`);
      if (response.ok) renderChat(await response.json());
      await refreshThreads();
    } catch {}
    if (!state.completed && !stopRequested) conversationStatus.textContent = "Turn ended without a final response.";
    if (stopRequested) conversationStatus.textContent = "Generation stopped";
    stopRequested = false;
    messageInput.focus();
  }
}

async function loadHistory() {
  try {
    const response = await fetch("/api/investigations");
    if (!response.ok) throw new Error();
    const items = await response.json();
    historyList.replaceChildren();
    historyStatus.textContent = items.length ? "Archived reports from the previous investigation workflow" : "No archived investigations yet.";
    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `${formatSavedDate(item.created_at)} · ${item.scenario} · Alert ${formatUtc(item.alert_time)}`;
      button.addEventListener("click", async () => {
        try {
          const savedResponse = await fetch(`/api/investigations/${item.id}`);
          const saved = await savedResponse.json();
          if (!savedResponse.ok) throw new Error(saved.error || "Could not open archived report.");
          legacyReport.innerHTML = saved.report_html;
          legacyMeta.textContent = `${saved.scenario} · ${formatUtc(saved.alert?.timestamp)} · ${saved.model} · ${saved.calls} requests · ${saved.tokens ?? "unknown"} tokens`;
          legacyTrace.textContent = JSON.stringify(saved.trace, null, 2);
          legacyDialog.showModal();
        } catch (error) {
          historyStatus.textContent = error.message;
        }
      });
      historyList.append(button);
    }
  } catch {
    historyStatus.textContent = "Archived reports could not be loaded.";
  }
}

function openProviderDialog() {
  providerDialogError.textContent = "";
  providerModelInput.value = providerModel;
  providerForget.hidden = !providerConfigured;
  providerDialog.showModal();
}

function closeProviderDialog() {
  if (providerDialog.open) providerDialog.close();
}

async function forgetProviderSession() {
  providerForget.disabled = true;
  try {
    const response = await fetch("/api/provider/session", { method: "DELETE" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not clear session settings.");
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
      method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ api_key: apiKey, model }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not configure OpenRouter.");
    providerConfigured = Boolean(result.configured);
    providerModel = result.model || model;
    closeProviderDialog();
    updateProviderStatus();
    conversationStatus.textContent = "Session ready. Press Send when you want to start a request.";
  } catch (error) {
    providerDialogError.textContent = error.message;
  } finally {
    providerSubmit.disabled = false;
    providerCancel.disabled = false;
    providerForget.disabled = false;
  }
}

chart.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  const rows = data[sensor] || [];
  if (!rows.length) return;
  event.preventDefault();
  const current = highlighted?.sensor === sensor ? rows.findIndex((row) => row.timestamp === highlighted.timestamp) : -1;
  const index = Math.max(0, Math.min(rows.length - 1, current + (event.key === "ArrowRight" ? 1 : -1)));
  highlighted = { ...rows[index], sensor };
  drawChart();
});

sensorButtons.forEach((button) => button.addEventListener("click", () => {
  sensor = button.dataset.sensor;
  sensorButtons.forEach((tab) => {
    const active = tab.dataset.sensor === sensor;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-pressed", String(active));
  });
  drawChart(true);
}));

function handlePlotlyClick(event) {
  const row = event.points[0]?.customdata;
  if (!row) return;
  const alert = (data.alerts || []).find((item) => item.timestamp === row.timestamp);
  if (alert) {
    chooseAlert(alert);
    return;
  }
  highlighted = { ...row, sensor };
  drawChart();
}

document.querySelector("#clear-context").addEventListener("click", async () => {
  try { await saveContext(null); }
  catch (error) { contextStatus.textContent = error.message; }
});

datasetSelect.addEventListener("change", () => loadDataset(datasetSelect.value));
document.querySelector("#new-chat").addEventListener("click", async () => {
  try {
    await createThread();
    chatTitle.textContent = "New chat";
    welcomeMessage();
    conversationStatus.textContent = "New conversation · select an alert or ask about any dataset.";
    await refreshThreads();
    messageInput.focus();
  } catch (error) {
    conversationStatus.textContent = error.message;
  }
});

chatForm.addEventListener("submit", sendMessage);
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});
stopButton.addEventListener("click", () => {
  if (!controller) return;
  stopRequested = true;
  stopButton.disabled = true;
  conversationStatus.textContent = "Stopping generation…";
  controller.abort();
});
providerSettings.addEventListener("click", openProviderDialog);
providerClose.addEventListener("click", closeProviderDialog);
providerCancel.addEventListener("click", closeProviderDialog);
providerForget.addEventListener("click", forgetProviderSession);
providerForm.addEventListener("submit", saveProviderSession);
providerDialog.addEventListener("close", () => {
  providerKey.value = "";
  providerDialogError.textContent = "";
});
document.querySelector("#legacy-close").addEventListener("click", () => legacyDialog.close());
legacyReport.addEventListener("click", (event) => {
  const link = event.target.closest('a[href^="#evidence-"]');
  if (!link || !/^#evidence-\d+$/.test(link.getAttribute("href"))) return;
  const evidence = legacyReport.querySelector(link.getAttribute("href"));
  if (!evidence) return;
  evidence.open = true;
  evidence.scrollIntoView({ block: "center" });
});

search.addEventListener("submit", async (event) => {
  event.preventDefault();
  searchButton.disabled = true;
  searchStatus.textContent = "Searching…";
  results.replaceChildren();
  try {
    const response = await fetch(`/api/documents?q=${encodeURIComponent(query.value)}`);
    const documents = await response.json();
    if (!response.ok) throw new Error(documents.error || "Search unavailable. Try again later.");
    searchStatus.textContent = documents.length ? `${documents.length} sections found · semantic search` : "No applicable evidence found. Try a more specific question.";
    renderDocuments(documents, true);
  } catch (error) {
    searchStatus.textContent = error instanceof TypeError ? "Search unavailable. Check the local server and try again." : error.message;
  } finally {
    searchButton.disabled = false;
  }
});

chatMessages.addEventListener("click", (event) => {
  const link = event.target.closest("a.chat-citation");
  if (!link) return;
  const message = link.closest(".assistant-message");
  const evidence = message?.querySelector(link.getAttribute("href"));
  if (evidence) {
    evidence.open = true;
    evidence.scrollIntoView({ block: "center", behavior: "smooth" });
  }
});

async function initialize() {
  renderDocuments(data.documents);
  await updateContextUI();
  chart.on("plotly_click", handlePlotlyClick);
  await loadHistory();
  try {
    await refreshThreads();
    if (currentThreads.length) await openThread(currentThreads[0].id);
    else welcomeMessage();
  } catch (error) {
    conversationStatus.textContent = error.message;
    welcomeMessage();
  }
  updateProviderStatus();
}

initialize();
