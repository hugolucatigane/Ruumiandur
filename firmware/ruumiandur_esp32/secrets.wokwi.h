#pragma once

// build-wokwi.ps1 loob selle eiratava päisefaili. Wokwi peab kasutama oma
// sisseehitatud pääsupunkti, kuid API_URL tuleb endiselt failist firmware/ruumiandur/secrets.h.
#include "secrets.wokwi.generated.h"

// Wokwi sisseehitatud privaatne lüüs suunab API_URL-i hosti kohalikku võrku.
constexpr bool WOKWI_POST_TO_API = true;
