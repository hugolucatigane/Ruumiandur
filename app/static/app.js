const elements = {
  deviceId: document.querySelector("#device-id"),
  refreshButton: document.querySelector("#refresh-button"),
  statusDot: document.querySelector("#status-dot"),
  statusLabel: document.querySelector("#status-label"),
  statusMessage: document.querySelector("#status-message"),
  lastUpdate: document.querySelector("#last-update"),
  temperatureValue: document.querySelector("#temperature-value"),
  humidityValue: document.querySelector("#humidity-value"),
  gasValue: document.querySelector("#gas-value"),
  temperatureQuality: document.querySelector("#temperature-quality"),
  humidityQuality: document.querySelector("#humidity-quality"),
  gasQuality: document.querySelector("#gas-quality"),
  temperatureRange: document.querySelector("#temperature-range"),
  humidityRange: document.querySelector("#humidity-range"),
  gasRange: document.querySelector("#gas-range"),
  qualityValue: document.querySelector("#quality-value"),
  qualityDetail: document.querySelector("#quality-detail"),
  sampleCount: document.querySelector("#sample-count"),
  temperatureChart: document.querySelector("#temperature-chart"),
  humidityChart: document.querySelector("#humidity-chart"),
  gasChart: document.querySelector("#gas-chart"),
  temperatureChartRange: document.querySelector("#temperature-chart-range"),
  humidityChartRange: document.querySelector("#humidity-chart-range"),
  gasChartRange: document.querySelector("#gas-chart-range"),
  rows: document.querySelector("#reading-rows"),
  summaryPeriod: document.querySelector("#summary-period"),
  summaryButton: document.querySelector("#summary-button"),
  summaryText: document.querySelector("#summary-text"),
  summaryMeta: document.querySelector("#summary-meta"),
  anomalyList: document.querySelector("#anomaly-list"),
};

let latestReadings = [];
let latestThresholds = null;

function deviceId() {
  return elements.deviceId.value.trim() || "esp32-bedroom-1";
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
    latestThresholds = status.thresholds;
    renderStatus(status);
    renderThresholds(latestThresholds);
    renderReadings(latestReadings, latestThresholds, status.sensor_warnings || []);
  } catch (error) {
    renderFetchError(error);
  } finally {
    elements.refreshButton.disabled = false;
  }
}

function renderStatus(status) {
  const labels = { online: "Andur on ühendatud", degraded: "Andmete kvaliteediprobleem", offline: "Andur ei vasta", unknown: "Andmed puuduvad" };
  const sensorWarnings = status.sensor_warnings || [];
  elements.statusDot.className = `status-dot ${status.state}`;
  elements.statusLabel.textContent = labels[status.state] || status.state;
  elements.statusMessage.textContent = status.message;
  elements.qualityValue.textContent = sensorWarnings.length
    ? "Kahtlane mõõtekanal"
    : status.state === "online" ? "Kehtiv voog" : labels[status.state] || "Kontrolli andurit";
  const warningDetail = sensorWarnings.length ? `Kinni jäänud kanaleid: ${sensorWarnings.length} · ` : "";
  elements.qualityDetail.textContent = `${warningDetail}Vigaseid sõnumeid 24 h jooksul: ${status.rejected_last_24h}`;
}

function renderThresholds(thresholds) {
  const [temperatureMinimum, temperatureMaximum] = thresholds.temperature_c;
  const [humidityMinimum, humidityMaximum] = thresholds.humidity_pct;
  const [, gasMaximum] = thresholds.gas_level_pct;
  elements.temperatureRange.textContent = `Eelistatud unevahemik ${temperatureMinimum}–${temperatureMaximum} °C`;
  elements.humidityRange.textContent = `Eelistatud unevahemik ${humidityMinimum}–${humidityMaximum}%`;
  elements.gasRange.textContent = `Hoiatuspiir ${gasMaximum}% · suhteline signaal, mitte ppm`;
}

function renderReadings(readings, thresholds, sensorWarnings = []) {
  elements.sampleCount.textContent = `${readings.length} väärtust`;
  if (!readings.length) {
    elements.temperatureValue.textContent = "—";
    elements.humidityValue.textContent = "—";
    elements.gasValue.textContent = "—";
    elements.lastUpdate.textContent = "Viimane mõõtmine: —";
    setTag(elements.temperatureQuality, { label: "—", className: "" });
    setTag(elements.humidityQuality, { label: "—", className: "" });
    setTag(elements.gasQuality, { label: "—", className: "" });
    elements.rows.innerHTML = '<tr><td colspan="6" class="empty-cell">Andmed puuduvad.</td></tr>';
    drawLine(elements.temperatureChart, [], "temperature_c", "#c76526", elements.temperatureChartRange, "°C");
    drawLine(elements.humidityChart, [], "humidity_pct", "#256b9b", elements.humidityChartRange, "%");
    drawLine(elements.gasChart, [], "gas_level_pct", "#b83e3e", elements.gasChartRange, "%");
    return;
  }

  const latest = readings[0];
  const stuckCodes = new Set(sensorWarnings.map((warning) => warning.code));
  elements.temperatureValue.textContent = Number(latest.temperature_c).toFixed(1);
  elements.humidityValue.textContent = Number(latest.humidity_pct).toFixed(1);
  elements.gasValue.textContent = latest.gas_level_pct == null ? "—" : Number(latest.gas_level_pct).toFixed(1);
  elements.lastUpdate.textContent = `Viimane mõõtmine: ${formatTime(latest.measured_at)}`;
  setTag(
    elements.temperatureQuality,
    stuckCodes.has("temperature_stuck")
      ? { label: "näit ei muutu", className: "warning" }
      : classify(latest.temperature_c, ...thresholds.temperature_c),
  );
  setTag(
    elements.humidityQuality,
    stuckCodes.has("humidity_stuck")
      ? { label: "näit ei muutu", className: "warning" }
      : classify(latest.humidity_pct, ...thresholds.humidity_pct),
  );
  if (latest.gas_level_pct == null) {
    setTag(elements.gasQuality, { label: "andmed puuduvad", className: "" });
  } else if (latest.gas_warmup) {
    setTag(elements.gasQuality, { label: "soojeneb", className: "warning" });
  } else if (stuckCodes.has("gas_stuck")) {
    setTag(elements.gasQuality, { label: "näit ei muutu", className: "warning" });
  } else {
    setTag(elements.gasQuality, classify(latest.gas_level_pct, ...thresholds.gas_level_pct));
  }

  const ascending = [...readings].reverse();
  drawLine(elements.temperatureChart, ascending, "temperature_c", "#c76526", elements.temperatureChartRange, "°C");
  drawLine(elements.humidityChart, ascending, "humidity_pct", "#256b9b", elements.humidityChartRange, "%");
  const gasReadings = ascending.filter((reading) => reading.gas_level_pct != null && !reading.gas_warmup);
  drawLine(elements.gasChart, gasReadings, "gas_level_pct", "#b83e3e", elements.gasChartRange, "%");
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
      formatTime(reading.measured_at),
      `${Number(reading.temperature_c).toFixed(1)} °C`,
      `${Number(reading.humidity_pct).toFixed(1)}%`,
      reading.gas_level_pct == null ? "—" : `${Number(reading.gas_level_pct).toFixed(1)}% (${reading.gas_raw})`,
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
      ollama: "kohalik Ollama",
      openai: "OpenAI",
      rules_no_api_key: "reeglipõhine varuvariant (API võti puudub)",
      rules_ai_error: "reeglipõhine varuvariant (AI teenus ei vastanud)",
      rules_no_ai_available: "reeglipõhine varuvariant (AI pole saadaval)",
      rules_insufficient_coverage: "reeglipõhine (andmekatvus on ebapiisav)",
      rules_sensor_quality: "reeglipõhine (anduri kvaliteedihoiatus)",
      rules_requested: "reeglipõhine",
    };
    const coverageLabel = report.coverage_sufficient ? "Katvus" : "Ebapiisav katvus";
    const inputMeta = ["rules_insufficient_coverage", "rules_sensor_quality"].includes(report.summary_source)
      ? "AI-d ei kasutatud"
      : `AI sisend ${report.ai_input_bytes} baiti`;
    elements.summaryMeta.textContent = `${coverageLabel}: ${report.sample_count}/${report.expected_sample_count} (${Number(report.coverage_percent).toFixed(1)}%) · Allikas: ${sources[report.summary_source] || report.summary_source} · ${inputMeta}`;
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
window.addEventListener("resize", () => renderReadings(latestReadings, latestThresholds));

refresh();
window.setInterval(refresh, 5000);
