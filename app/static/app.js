const elements = {
  deviceId: document.querySelector("#device-id"),
  refreshButton: document.querySelector("#refresh-button"),
  statusDot: document.querySelector("#status-dot"),
  statusLabel: document.querySelector("#status-label"),
  statusMessage: document.querySelector("#status-message"),
  roomLabel: document.querySelector("#room-label"),
  lastUpdate: document.querySelector("#last-update"),
  temperatureValue: document.querySelector("#temperature-value"),
  humidityValue: document.querySelector("#humidity-value"),
  temperatureQuality: document.querySelector("#temperature-quality"),
  humidityQuality: document.querySelector("#humidity-quality"),
  qualityValue: document.querySelector("#quality-value"),
  qualityDetail: document.querySelector("#quality-detail"),
  sampleCount: document.querySelector("#sample-count"),
  temperatureChart: document.querySelector("#temperature-chart"),
  humidityChart: document.querySelector("#humidity-chart"),
  temperatureChartRange: document.querySelector("#temperature-chart-range"),
  humidityChartRange: document.querySelector("#humidity-chart-range"),
  rows: document.querySelector("#reading-rows"),
  summaryPeriod: document.querySelector("#summary-period"),
  summaryButton: document.querySelector("#summary-button"),
  summaryText: document.querySelector("#summary-text"),
  summaryMeta: document.querySelector("#summary-meta"),
  anomalyList: document.querySelector("#anomaly-list"),
};

let latestReadings = [];

function deviceId() {
  return elements.deviceId.value.trim() || "esp8266-bedroom-1";
}

async function getJson(path, parameters = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(parameters).forEach(([key, value]) => url.searchParams.set(key, value));
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function formatTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("et-EE", {
    timeZone: "Europe/Tallinn",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function classify(value, minimum, maximum) {
  if (value < minimum) return { label: "liiga madal", className: "warning" };
  if (value > maximum) return { label: "liiga kõrge", className: "warning" };
  return { label: "piirides", className: "good" };
}

function setTag(element, classification) {
  element.textContent = classification.label;
  element.className = `tag ${classification.className}`;
}

async function refresh() {
  elements.refreshButton.disabled = true;
  try {
    const [readingPayload, status] = await Promise.all([
      getJson("/api/readings", { device_id: deviceId(), limit: 120, minutes: 60 }),
      getJson("/api/status", { device_id: deviceId() }),
    ]);
    latestReadings = readingPayload.readings;
    renderStatus(status);
    renderReadings(latestReadings);
  } catch (error) {
    renderFetchError(error);
  } finally {
    elements.refreshButton.disabled = false;
  }
}

function renderStatus(status) {
  const labels = { online: "Andur on ühendatud", degraded: "Andmete kvaliteediprobleem", offline: "Andur ei vasta", unknown: "Andmed puuduvad" };
  elements.statusDot.className = `status-dot ${status.state}`;
  elements.statusLabel.textContent = labels[status.state] || status.state;
  elements.statusMessage.textContent = status.message;
  elements.qualityValue.textContent = status.state === "online" ? "Kehtiv voog" : labels[status.state] || "Kontrolli andurit";
  elements.qualityDetail.textContent = `Vigaseid sõnumeid 24 h jooksul: ${status.rejected_last_24h}`;
}

function renderReadings(readings) {
  elements.sampleCount.textContent = `${readings.length} väärtust`;
  if (!readings.length) {
    elements.temperatureValue.textContent = "—";
    elements.humidityValue.textContent = "—";
    elements.roomLabel.textContent = "—";
    elements.lastUpdate.textContent = "Viimane mõõtmine: —";
    setTag(elements.temperatureQuality, { label: "—", className: "" });
    setTag(elements.humidityQuality, { label: "—", className: "" });
    elements.rows.innerHTML = '<tr><td colspan="5" class="empty-cell">Andmed puuduvad.</td></tr>';
    drawLine(elements.temperatureChart, [], "temperature_c", "#c76526", elements.temperatureChartRange, "°C");
    drawLine(elements.humidityChart, [], "humidity_pct", "#256b9b", elements.humidityChartRange, "%");
    return;
  }

  const latest = readings[0];
  elements.temperatureValue.textContent = Number(latest.temperature_c).toFixed(1);
  elements.humidityValue.textContent = Number(latest.humidity_pct).toFixed(1);
  elements.roomLabel.textContent = `${latest.room} · ${latest.simulated ? "simulaator" : "pärisandur"}`;
  elements.lastUpdate.textContent = `Viimane mõõtmine: ${formatTime(latest.received_at)}`;
  setTag(elements.temperatureQuality, classify(latest.temperature_c, 18, 24));
  setTag(elements.humidityQuality, classify(latest.humidity_pct, 30, 60));

  const ascending = [...readings].reverse();
  drawLine(elements.temperatureChart, ascending, "temperature_c", "#c76526", elements.temperatureChartRange, "°C");
  drawLine(elements.humidityChart, ascending, "humidity_pct", "#256b9b", elements.humidityChartRange, "%");
  renderTable(readings.slice(0, 8));
}

function drawLine(canvas, readings, key, color, rangeElement, unit) {
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(280, canvas.clientWidth);
  const height = Math.max(100, canvas.clientHeight);
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);

  if (!readings.length) {
    context.fillStyle = "#879399";
    context.font = "12px system-ui";
    context.fillText("Andmeid pole", 14, height / 2);
    rangeElement.textContent = "—";
    return;
  }

  const values = readings.map((reading) => Number(reading[key]));
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const padding = Math.max((rawMax - rawMin) * 0.16, key === "temperature_c" ? 0.6 : 2);
  const minimum = rawMin - padding;
  const maximum = rawMax + padding;
  const left = 8;
  const right = width - 8;
  const top = 8;
  const bottom = height - 8;

  context.strokeStyle = "#dfe8e8";
  context.lineWidth = 1;
  for (let index = 1; index < 4; index += 1) {
    const y = top + ((bottom - top) * index) / 4;
    context.beginPath();
    context.moveTo(left, y);
    context.lineTo(right, y);
    context.stroke();
  }

  context.strokeStyle = color;
  context.lineWidth = 2.25;
  context.lineJoin = "round";
  context.lineCap = "round";
  context.beginPath();
  values.forEach((value, index) => {
    const x = values.length === 1 ? width / 2 : left + ((right - left) * index) / (values.length - 1);
    const y = bottom - ((value - minimum) / (maximum - minimum)) * (bottom - top);
    if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
  });
  context.stroke();
  rangeElement.textContent = `${rawMin.toFixed(1)}–${rawMax.toFixed(1)} ${unit}`;
}

function renderTable(readings) {
  elements.rows.replaceChildren();
  readings.forEach((reading) => {
    const row = document.createElement("tr");
    const values = [
      formatTime(reading.received_at),
      `${Number(reading.temperature_c).toFixed(1)} °C`,
      `${Number(reading.humidity_pct).toFixed(1)}%`,
      reading.mode,
      `#${reading.seq}`,
    ];
    values.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    elements.rows.appendChild(row);
  });
}

async function createSummary() {
  elements.summaryButton.disabled = true;
  elements.summaryButton.textContent = "Koostan…";
  try {
    const report = await getJson("/api/summary", {
      device_id: deviceId(),
      hours: elements.summaryPeriod.value,
      use_ai: true,
    });
    elements.summaryText.textContent = report.summary;
    const sources = {
      openai: "OpenAI",
      rules_no_api_key: "reeglipõhine varuvariant (API võti puudub)",
      rules_ai_error: "reeglipõhine varuvariant (AI teenus ei vastanud)",
      rules_requested: "reeglipõhine",
    };
    elements.summaryMeta.textContent = `Allikas: ${sources[report.summary_source] || report.summary_source} · AI sisend ${report.ai_input_bytes} baiti`;
    renderAnomalies(report.anomalies);
  } catch (error) {
    elements.summaryText.textContent = `Kokkuvõtet ei saanud laadida: ${error.message}`;
  } finally {
    elements.summaryButton.disabled = false;
    elements.summaryButton.textContent = "Koosta kokkuvõte";
  }
}

function renderAnomalies(anomalies) {
  elements.anomalyList.replaceChildren();
  anomalies.forEach((anomaly) => {
    const item = document.createElement("div");
    item.className = `anomaly ${anomaly.severity}`;
    item.textContent = anomaly.message;
    elements.anomalyList.appendChild(item);
  });
}

function renderFetchError(error) {
  elements.statusDot.className = "status-dot offline";
  elements.statusLabel.textContent = "Teenusega ei saa ühendust";
  elements.statusMessage.textContent = error.message;
}

elements.refreshButton.addEventListener("click", refresh);
elements.summaryButton.addEventListener("click", createSummary);
elements.deviceId.addEventListener("change", refresh);
window.addEventListener("resize", () => renderReadings(latestReadings));

refresh();
window.setInterval(refresh, 5000);
