#pragma once

// Kopeeri see fail nimega secrets.h ja asenda näidisväärtused.
// AI seadistused jäävad projekti juurkausta .env-faili ja neid ei kirjutata seadmesse.
const char* WIFI_SSID = "OMA_WIFI_NIMI";
const char* WIFI_PASSWORD = "OMA_WIFI_PAROOL";

// Kasuta sülearvuti LAN-i IPv4-aadressi, mitte localhosti. Näide: http://192.168.1.42:8000/api/readings
const char* API_URL = "http://192.168.1.42:8000/api/readings";
