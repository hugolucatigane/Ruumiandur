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

char bootId[9];
uint32_t sequenceNumber = 0;
uint32_t lastSampleAt = 0;
uint32_t lastWifiAttemptAt = 0;
uint32_t anomalyStartedAt = 0;
bool anomalyActive = false;
bool junkNext = false;
bool previousButtonState = HIGH;
bool wifiAttemptStarted = false;
bool wifiWasConnected = false;

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

float noise(float amplitude) {
  const int32_t value = static_cast<int32_t>(platformRandom() % 2001) - 1000;
  return (static_cast<float>(value) / 1000.0f) * amplitude;
}

void simulateMeasurement(uint32_t now, float& temperature, float& humidity, const char*& mode) {
  const float phase = (static_cast<float>(now % 600000UL) / 600000.0f) * 2.0f * PI;
  temperature = 21.2f + 0.45f * sinf(phase) + noise(0.12f);
  humidity = 45.0f + 2.0f * sinf(phase + 1.3f) + noise(0.5f);
  mode = "normal";

  if (isAnomalyActive(now)) {
    // A plausible heat event: still physically valid, but outside the configured comfort band.
    temperature += 6.3f;
    humidity += 8.0f;
    mode = "anomaly";
  }

  if (junkNext) {
    // Intentionally impossible for the selected payload contract. The service must reject it.
    temperature = 999.0f;
    mode = "fault";
    junkNext = false;
  }
}

void sendMeasurement(float temperature, float humidity, const char* mode) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("Send skipped: Wi-Fi is %s\n", wifiStatusName(WiFi.status()));
    return;
  }

  char payload[384];
  snprintf(
    payload,
    sizeof(payload),
    "{\"device_id\":\"esp8266-bedroom-1\",\"boot_id\":\"%s\",\"room\":\"Magamistuba\","
    "\"seq\":%lu,\"uptime_ms\":%lu,\"temperature_c\":%.2f,\"humidity_pct\":%.2f,"
    "\"simulated\":true,\"mode\":\"%s\"}",
    bootId,
    static_cast<unsigned long>(sequenceNumber),
    static_cast<unsigned long>(millis()),
    temperature,
    humidity,
    mode
  );

  WiFiClient client;
  HTTPClient http;
#if defined(ESP32)
  http.setConnectTimeout(3000);
#endif
  http.setTimeout(5000);
  if (!http.begin(client, API_URL)) {
    Serial.println("Send failed: invalid API URL");
    return;
  }
  http.addHeader("Content-Type", "application/json");
  const int responseCode = http.POST(reinterpret_cast<uint8_t*>(payload), strlen(payload));
  const String responseBody = responseCode > 0 ? http.getString() : http.errorToString(responseCode);

  Serial.printf(
    "POST seq=%lu mode=%s temp=%.2f humidity=%.2f -> HTTP %d %s\n",
    static_cast<unsigned long>(sequenceNumber),
    mode,
    temperature,
    humidity,
    responseCode,
    responseBody.c_str()
  );
  http.end();
  sequenceNumber++;
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
  } else if (command == 'j') {
    junkNext = true;
    Serial.println("Simulator: next payload will contain junk data");
  } else if (command == 'n') {
    anomalyActive = false;
    Serial.println("Simulator: normal mode");
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  snprintf(bootId, sizeof(bootId), "%08lx", static_cast<unsigned long>(platformRandom()));
  Serial.printf("Ruumiandur boot_id=%s\n", bootId);
  Serial.println("Commands: a=anomaly, j=junk payload, n=normal");
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
    const char* mode = "normal";
    simulateMeasurement(now, temperature, humidity, mode);
    sendMeasurement(temperature, humidity, mode);
  }

  delay(10);
}
