#if defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
  #include <osapi.h>
#elif defined(ESP32)
  #include <WiFi.h>
  #include <HTTPClient.h>
  #include <esp_system.h>
#else
  #error "This sketch supports ESP8266 and ESP32 boards. Select the correct board in Arduino IDE."
#endif
#include <math.h>

#include "secrets.h"

// ESP8266 NodeMCU FLASH and classic ESP32 BOOT buttons normally use GPIO0.
// Change this if your development board maps its button elsewhere.
constexpr uint8_t BUTTON_PIN = 0;
constexpr uint32_t SAMPLE_INTERVAL_MS = 10000;
constexpr uint32_t ANOMALY_DURATION_MS = 60000;
constexpr uint32_t WIFI_RETRY_MS = 15000;
constexpr uint32_t UPLOAD_RETRY_MS = 5000;
constexpr size_t MEASUREMENT_QUEUE_CAPACITY = 120;

struct BufferedMeasurement {
  uint32_t sequence;
  uint32_t measuredUptimeMs;
  float temperature;
  float humidity;
  uint16_t gasRaw;
  float gasLevelPct;
  char mode[8];
};

enum class SendResult : uint8_t {
  accepted,
  retry,
  rejected,
};

char bootId[9];
uint32_t sequenceNumber = 0;
uint32_t lastSampleAt = 0;
uint32_t lastWifiAttemptAt = 0;
uint32_t lastUploadAttemptAt = 0;
uint32_t anomalyStartedAt = 0;
uint32_t gasAnomalyStartedAt = 0;
BufferedMeasurement measurementQueue[MEASUREMENT_QUEUE_CAPACITY];
size_t queueHead = 0;
size_t queueCount = 0;
bool anomalyActive = false;
bool gasAnomalyActive = false;
bool junkNext = false;
bool previousButtonState = HIGH;
bool wifiAttemptStarted = false;
bool wifiWasConnected = false;
bool uploadBackoffActive = false;

uint32_t platformRandom() {
#if defined(ESP8266)
  return static_cast<uint32_t>(os_random());
#else
  return esp_random();
#endif
}

const char* wifiStatusName(int status) {
  switch (status) {
    case WL_IDLE_STATUS: return "connecting";
    case WL_NO_SSID_AVAIL: return "SSID not found";
    case WL_CONNECTED: return "connected";
    case WL_CONNECT_FAILED: return "connection failed";
    case WL_CONNECTION_LOST: return "connection lost";
    case WL_WRONG_PASSWORD: return "wrong password";
    case WL_DISCONNECTED: return "disconnected";
    default: return "unknown";
  }
}

void connectWifi() {
  const int status = WiFi.status();
  if (status == WL_CONNECTED) {
    if (!wifiWasConnected) {
      wifiWasConnected = true;
      Serial.printf(
        "Wi-Fi connected: IP=%s RSSI=%d dBm\n",
        WiFi.localIP().toString().c_str(),
        WiFi.RSSI()
      );
    }
    return;
  }

  if (wifiWasConnected) {
    wifiWasConnected = false;
    Serial.printf("Wi-Fi lost: %s\n", wifiStatusName(status));
  }

  const uint32_t now = millis();
  if (wifiAttemptStarted && now - lastWifiAttemptAt < WIFI_RETRY_MS) return;
  wifiAttemptStarted = true;
  lastWifiAttemptAt = now;

  Serial.printf("Wi-Fi: connecting to %s (previous status: %s)\n", WIFI_SSID, wifiStatusName(status));
  WiFi.mode(WIFI_STA);
#if defined(ESP8266)
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
#endif
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

bool isAnomalyActive(uint32_t now) {
  if (anomalyActive && now - anomalyStartedAt >= ANOMALY_DURATION_MS) {
    anomalyActive = false;
    Serial.println("Simulator: anomaly ended");
  }
  return anomalyActive;
}

bool isGasAnomalyActive(uint32_t now) {
  if (gasAnomalyActive && now - gasAnomalyStartedAt >= ANOMALY_DURATION_MS) {
    gasAnomalyActive = false;
    Serial.println("MQ-2 simulator: gas anomaly ended");
  }
  return gasAnomalyActive;
}

float noise(float amplitude) {
  const int32_t value = static_cast<int32_t>(platformRandom() % 2001) - 1000;
  return (static_cast<float>(value) / 1000.0f) * amplitude;
}

void simulateMeasurement(
  uint32_t now,
  float& temperature,
  float& humidity,
  uint16_t& gasRaw,
  float& gasLevelPct,
  const char*& mode
) {
  const float phase = (static_cast<float>(now % 600000UL) / 600000.0f) * 2.0f * PI;
  temperature = 21.2f + 0.45f * sinf(phase) + noise(0.12f);
  humidity = 45.0f + 2.0f * sinf(phase + 1.3f) + noise(0.5f);
  gasLevelPct = 16.0f + 2.5f * sinf(phase + 2.1f) + noise(1.0f);
  mode = "normal";

  if (isAnomalyActive(now)) {
    // A plausible heat event: still physically valid, but outside the configured comfort band.
    temperature += 6.3f;
    humidity += 8.0f;
    mode = "anomaly";
  }

  if (isGasAnomalyActive(now)) {
    // Relative MQ-2 signal only. It is intentionally not presented as calibrated ppm.
    gasLevelPct = 82.0f + noise(3.0f);
    mode = "anomaly";
  }

  gasLevelPct = constrain(gasLevelPct, 0.0f, 100.0f);
  gasRaw = static_cast<uint16_t>(lroundf((gasLevelPct / 100.0f) * 1023.0f));

  if (junkNext) {
    // Intentionally impossible for the selected payload contract. The service must reject it.
    temperature = 999.0f;
    mode = "fault";
    junkNext = false;
  }
}

void enqueueMeasurement(
  uint32_t measuredUptimeMs,
  float temperature,
  float humidity,
  uint16_t gasRaw,
  float gasLevelPct,
  const char* mode
) {
  if (queueCount == MEASUREMENT_QUEUE_CAPACITY) {
    Serial.printf(
      "Queue full: dropping oldest measurement seq=%lu\n",
      static_cast<unsigned long>(measurementQueue[queueHead].sequence)
    );
    queueHead = (queueHead + 1) % MEASUREMENT_QUEUE_CAPACITY;
    queueCount--;
  }

  BufferedMeasurement& measurement =
    measurementQueue[(queueHead + queueCount) % MEASUREMENT_QUEUE_CAPACITY];
  measurement.sequence = sequenceNumber++;
  measurement.measuredUptimeMs = measuredUptimeMs;
  measurement.temperature = temperature;
  measurement.humidity = humidity;
  measurement.gasRaw = gasRaw;
  measurement.gasLevelPct = gasLevelPct;
  snprintf(measurement.mode, sizeof(measurement.mode), "%s", mode);
  queueCount++;

  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf(
      "Queued seq=%lu while Wi-Fi is %s (%u/%u buffered)\n",
      static_cast<unsigned long>(measurement.sequence),
      wifiStatusName(WiFi.status()),
      static_cast<unsigned int>(queueCount),
      static_cast<unsigned int>(MEASUREMENT_QUEUE_CAPACITY)
    );
  }
}

SendResult sendMeasurement(const BufferedMeasurement& measurement) {
  const uint32_t sentUptimeMs = millis();
  char payload[512];
  snprintf(
    payload,
    sizeof(payload),
    "{\"device_id\":\"esp8266-bedroom-1\",\"boot_id\":\"%s\","
    "\"seq\":%lu,\"uptime_ms\":%lu,\"sent_uptime_ms\":%lu,"
    "\"temperature_c\":%.2f,\"humidity_pct\":%.2f,"
    "\"gas_raw\":%u,\"gas_level_pct\":%.2f,\"gas_source\":\"simulated\","
    "\"gas_warmup\":false,\"simulated\":true,\"mode\":\"%s\"}",
    bootId,
    static_cast<unsigned long>(measurement.sequence),
    static_cast<unsigned long>(measurement.measuredUptimeMs),
    static_cast<unsigned long>(sentUptimeMs),
    measurement.temperature,
    measurement.humidity,
    static_cast<unsigned int>(measurement.gasRaw),
    measurement.gasLevelPct,
    measurement.mode
  );

  WiFiClient client;
  HTTPClient http;
#if defined(ESP32)
  http.setConnectTimeout(3000);
#endif
  http.setTimeout(5000);
  if (!http.begin(client, API_URL)) {
    Serial.println("Send failed: invalid API URL");
    return SendResult::retry;
  }
  http.addHeader("Content-Type", "application/json");
  const int responseCode = http.POST(reinterpret_cast<uint8_t*>(payload), strlen(payload));
  const String responseBody = responseCode > 0 ? http.getString() : http.errorToString(responseCode);

  Serial.printf(
    "POST seq=%lu mode=%s temp=%.2f humidity=%.2f gas=%.1f%% raw=%u -> HTTP %d %s\n",
    static_cast<unsigned long>(measurement.sequence),
    measurement.mode,
    measurement.temperature,
    measurement.humidity,
    measurement.gasLevelPct,
    static_cast<unsigned int>(measurement.gasRaw),
    responseCode,
    responseBody.c_str()
  );
  http.end();
  if (responseCode >= 200 && responseCode < 300) return SendResult::accepted;
  if (responseCode == 408 || responseCode == 429) return SendResult::retry;
  if (responseCode >= 400 && responseCode < 500) return SendResult::rejected;
  return SendResult::retry;
}

void flushMeasurementQueue(uint32_t now) {
  if (queueCount == 0 || WiFi.status() != WL_CONNECTED) return;
  if (uploadBackoffActive && now - lastUploadAttemptAt < UPLOAD_RETRY_MS) return;

  lastUploadAttemptAt = now;
  const SendResult result = sendMeasurement(measurementQueue[queueHead]);
  if (result == SendResult::retry) {
    uploadBackoffActive = true;
    return;
  }

  uploadBackoffActive = false;
  if (result == SendResult::rejected) {
    Serial.printf(
      "Dropping permanently rejected measurement seq=%lu\n",
      static_cast<unsigned long>(measurementQueue[queueHead].sequence)
    );
  }
  queueHead = (queueHead + 1) % MEASUREMENT_QUEUE_CAPACITY;
  queueCount--;
}

void handleButton(uint32_t now) {
  const bool currentState = digitalRead(BUTTON_PIN);
  if (previousButtonState == HIGH && currentState == LOW) {
    anomalyActive = true;
    anomalyStartedAt = now;
    Serial.println("Simulator: 60 second heat anomaly started");
  }
  previousButtonState = currentState;
}

void handleSerial(uint32_t now) {
  if (!Serial.available()) return;
  const char command = static_cast<char>(Serial.read());
  if (command == 'a') {
    anomalyActive = true;
    anomalyStartedAt = now;
    Serial.println("Simulator: anomaly started from Serial");
  } else if (command == 'g') {
    gasAnomalyActive = true;
    gasAnomalyStartedAt = now;
    Serial.println("MQ-2 simulator: 60 second gas anomaly started");
  } else if (command == 'j') {
    junkNext = true;
    Serial.println("Simulator: next payload will contain junk data");
  } else if (command == 'n') {
    anomalyActive = false;
    gasAnomalyActive = false;
    Serial.println("Simulator: normal mode");
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  snprintf(bootId, sizeof(bootId), "%08lx", static_cast<unsigned long>(platformRandom()));
  Serial.printf("Ruumiandur boot_id=%s\n", bootId);
  Serial.println("Commands: a=heat anomaly, g=MQ-2 gas anomaly, j=junk payload, n=normal");
  connectWifi();
  lastSampleAt = millis() - SAMPLE_INTERVAL_MS;
}

void loop() {
  const uint32_t now = millis();
  connectWifi();
  handleButton(now);
  handleSerial(now);

  if (now - lastSampleAt >= SAMPLE_INTERVAL_MS) {
    lastSampleAt = now;
    float temperature = 0.0f;
    float humidity = 0.0f;
    uint16_t gasRaw = 0;
    float gasLevelPct = 0.0f;
    const char* mode = "normal";
    simulateMeasurement(now, temperature, humidity, gasRaw, gasLevelPct, mode);
    enqueueMeasurement(now, temperature, humidity, gasRaw, gasLevelPct, mode);
  }

  flushMeasurementQueue(now);

  delay(10);
}
