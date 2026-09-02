#if !defined(ESP32)
  #error "Select an ESP32 board in Arduino IDE for this sketch."
#endif

#include <HTTPClient.h>
#include <WiFi.h>
#include <esp_system.h>
#include <math.h>

#if defined(WOKWI_SIMULATION)
  #include "secrets.wokwi.h"
#else
  #include "secrets.h"
#endif

// ESP32 DevKit / WROOM defaults. GPIO34 is an ADC1 input, so it remains usable
// while Wi-Fi is active. Change these if your board is wired differently.
constexpr uint8_t DHT22_PIN = 4;
constexpr uint8_t MQ2_ANALOG_PIN = 34;

constexpr uint32_t SAMPLE_INTERVAL_MS = 10000;
constexpr uint32_t WIFI_RETRY_MS = 15000;
constexpr uint32_t UPLOAD_RETRY_MS = 5000;
#if defined(WOKWI_SIMULATION)
constexpr uint32_t MQ2_STABILIZATION_MS = 15UL * 1000UL;
#else
constexpr uint32_t MQ2_STABILIZATION_MS = 5UL * 60UL * 1000UL;
#endif
constexpr uint8_t MQ2_SAMPLE_COUNT = 16;
constexpr size_t MEASUREMENT_QUEUE_CAPACITY = 120;

// gas_level_pct is a relative signal, not ppm. After the MQ-2 has completed its
// initial burn-in, replace these two values with readings measured in your own
// clean-air and chosen high-reference conditions.
constexpr uint16_t MQ2_REFERENCE_LOW_RAW = 0;
constexpr uint16_t MQ2_REFERENCE_HIGH_RAW = 4095;

constexpr char DEVICE_ID[] = "esp32-bedroom-1";

struct BufferedMeasurement {
  uint32_t sequence;
  uint32_t measuredUptimeMs;
  float temperature;
  float humidity;
  uint16_t gasRaw;
  float gasLevelPct;
  bool gasWarmup;
};

enum class SendResult : uint8_t {
  accepted,
  retry,
  rejected,
};

static_assert(
  MQ2_REFERENCE_HIGH_RAW > MQ2_REFERENCE_LOW_RAW,
  "MQ2_REFERENCE_HIGH_RAW must be greater than MQ2_REFERENCE_LOW_RAW"
);

char bootId[9];
uint32_t sequenceNumber = 0;
uint32_t bootStartedAt = 0;
uint32_t lastSampleAt = 0;
uint32_t lastWifiAttemptAt = 0;
uint32_t lastUploadAttemptAt = 0;
BufferedMeasurement measurementQueue[MEASUREMENT_QUEUE_CAPACITY];
size_t queueHead = 0;
size_t queueCount = 0;
bool wifiAttemptStarted = false;
bool wifiWasConnected = false;
bool uploadBackoffActive = false;

const char* wifiStatusName(int status) {
  switch (status) {
    case WL_IDLE_STATUS: return "connecting";
    case WL_NO_SSID_AVAIL: return "SSID not found";
    case WL_CONNECTED: return "connected";
    case WL_CONNECT_FAILED: return "connection failed";
    case WL_CONNECTION_LOST: return "connection lost";
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

  Serial.printf(
    "Wi-Fi: connecting to %s (previous status: %s)\n",
    WIFI_SSID,
    wifiStatusName(status)
  );
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
#if defined(WOKWI_SIMULATION)
  // Wokwi-GUEST always uses channel 6. Supplying it avoids a simulated scan.
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD, 6);
#else
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
#endif
}

// Measures how long the pin remains at level. DHT22 pulses are shorter than
// 100 microseconds, so a tight loop is more reliable than millisecond timing.
uint32_t measurePulse(uint8_t level, uint32_t timeoutUs) {
  const uint32_t startedAt = micros();
  while (digitalRead(DHT22_PIN) == level) {
    if (micros() - startedAt > timeoutUs) return 0;
  }
  return micros() - startedAt;
}

bool readDht22(float& temperature, float& humidity) {
  uint8_t data[5] = {0, 0, 0, 0, 0};
  bool validTiming = true;

  // Host start signal: at least 1 ms LOW, then release the bus. A 4.7-10 kOhm
  // external pull-up from DATA to 3.3 V is required for a bare DHT22.
  pinMode(DHT22_PIN, OUTPUT);
  digitalWrite(DHT22_PIN, LOW);
  delay(2);

  noInterrupts();
  pinMode(DHT22_PIN, INPUT_PULLUP);

  // Release-to-response HIGH, sensor response LOW, sensor response HIGH.
  validTiming = measurePulse(HIGH, 120) > 0;
  validTiming = validTiming && measurePulse(LOW, 120) > 0;
  validTiming = validTiming && measurePulse(HIGH, 120) > 0;

  for (uint8_t bit = 0; bit < 40 && validTiming; bit++) {
    const uint32_t lowDuration = measurePulse(LOW, 100);
    const uint32_t highDuration = measurePulse(HIGH, 120);
    if (lowDuration == 0 || highDuration == 0) {
      validTiming = false;
      break;
    }

    data[bit / 8] <<= 1;
    if (highDuration > 50) data[bit / 8] |= 1;
  }
  interrupts();

  if (!validTiming) return false;

  const uint8_t checksum = static_cast<uint8_t>(data[0] + data[1] + data[2] + data[3]);
  if (checksum != data[4]) return false;

  const uint16_t rawHumidity = (static_cast<uint16_t>(data[0]) << 8) | data[1];
  const uint16_t rawTemperature =
    (static_cast<uint16_t>(data[2] & 0x7f) << 8) | data[3];

  humidity = static_cast<float>(rawHumidity) / 10.0f;
  temperature = static_cast<float>(rawTemperature) / 10.0f;
  if ((data[2] & 0x80) != 0) temperature = -temperature;

  return isfinite(temperature)
    && isfinite(humidity)
    && temperature >= -40.0f
    && temperature <= 80.0f
    && humidity >= 0.0f
    && humidity <= 100.0f;
}

uint16_t readMq2Raw() {
  uint32_t total = 0;
  for (uint8_t sample = 0; sample < MQ2_SAMPLE_COUNT; sample++) {
    total += analogRead(MQ2_ANALOG_PIN);
    delay(2);
  }
  return static_cast<uint16_t>(total / MQ2_SAMPLE_COUNT);
}

float mq2RawToPercent(uint16_t raw) {
  const float percent =
    (static_cast<float>(raw) - MQ2_REFERENCE_LOW_RAW)
    * 100.0f
    / (MQ2_REFERENCE_HIGH_RAW - MQ2_REFERENCE_LOW_RAW);
  return constrain(percent, 0.0f, 100.0f);
}

void enqueueMeasurement(
  uint32_t measuredUptimeMs,
  float temperature,
  float humidity,
  uint16_t gasRaw,
  float gasLevelPct,
  bool gasWarmup
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
  measurement.gasWarmup = gasWarmup;
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
    "{\"device_id\":\"%s\",\"boot_id\":\"%s\","
    "\"seq\":%lu,\"uptime_ms\":%lu,\"sent_uptime_ms\":%lu,"
    "\"temperature_c\":%.2f,\"humidity_pct\":%.2f,"
    "\"gas_raw\":%u,\"gas_level_pct\":%.2f,\"gas_source\":\"mq2\","
    "\"gas_warmup\":%s,\"simulated\":false,\"mode\":\"normal\"}",
    DEVICE_ID,
    bootId,
    static_cast<unsigned long>(measurement.sequence),
    static_cast<unsigned long>(measurement.measuredUptimeMs),
    static_cast<unsigned long>(sentUptimeMs),
    measurement.temperature,
    measurement.humidity,
    static_cast<unsigned int>(measurement.gasRaw),
    measurement.gasLevelPct,
    measurement.gasWarmup ? "true" : "false"
  );

#if defined(WOKWI_SIMULATION)
  // Serial-only mode works with the free public gateway and still exposes the
  // exact API payload. Enable POSTs in secrets.wokwi.h when using a private
  // gateway that can resolve host.wokwi.internal.
  Serial.printf("JSON %s\n", payload);
  if (!WOKWI_POST_TO_API) return SendResult::accepted;
#endif

  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(3000);
  http.setTimeout(5000);
  if (!http.begin(client, API_URL)) {
    Serial.println("Send failed: invalid API URL");
    return SendResult::retry;
  }

  http.addHeader("Content-Type", "application/json");
  const int responseCode = http.POST(
    reinterpret_cast<uint8_t*>(payload),
    strlen(payload)
  );
  const String responseBody =
    responseCode > 0 ? http.getString() : http.errorToString(responseCode);

  Serial.printf(
    "POST seq=%lu temp=%.2f humidity=%.2f gas=%.1f%% raw=%u warmup=%s -> HTTP %d %s\n",
    static_cast<unsigned long>(measurement.sequence),
    measurement.temperature,
    measurement.humidity,
    measurement.gasLevelPct,
    static_cast<unsigned int>(measurement.gasRaw),
    measurement.gasWarmup ? "yes" : "no",
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

void sampleAndQueue(uint32_t now) {
  float temperature = 0.0f;
  float humidity = 0.0f;
  if (!readDht22(temperature, humidity)) {
    Serial.println("DHT22 read failed (timing, checksum, or value); payload skipped");
    return;
  }

  const uint16_t gasRaw = readMq2Raw();
  const float gasLevelPct = mq2RawToPercent(gasRaw);
  const bool gasWarmup = now - bootStartedAt < MQ2_STABILIZATION_MS;
  enqueueMeasurement(now, temperature, humidity, gasRaw, gasLevelPct, gasWarmup);
}

void setup() {
  Serial.begin(115200);
  delay(300);

  bootStartedAt = millis();
  snprintf(bootId, sizeof(bootId), "%08lx", static_cast<unsigned long>(esp_random()));

  pinMode(DHT22_PIN, INPUT_PULLUP);
  analogReadResolution(12);
  analogSetPinAttenuation(MQ2_ANALOG_PIN, ADC_11db);

  Serial.printf("Ruumiandur ESP32 boot_id=%s\n", bootId);
  Serial.printf("DHT22 GPIO=%u, MQ-2 ADC GPIO=%u\n", DHT22_PIN, MQ2_ANALOG_PIN);
  Serial.println("MQ-2 readings are marked warm-up for the first 5 minutes");
  connectWifi();

  // Give both sensors time to settle before the first sample.
  lastSampleAt = millis();
}

void loop() {
  const uint32_t now = millis();
  connectWifi();

  if (now - lastSampleAt >= SAMPLE_INTERVAL_MS) {
    lastSampleAt = now;
    sampleAndQueue(now);
  }

  flushMeasurementQueue(now);

  delay(10);
}
