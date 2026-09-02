# MQ-2 simulatsioon ja pärisanduri liides

Prototüüp ei vaja füüsilist MQ-2 andurit. ESP8266 genereerib iga 10 sekundi järel `gas_raw` väärtuse vahemikus 0–1023 ja sellest tuletatud `gas_level_pct` väärtuse vahemikus 0–100%. Tavarežiim püsib ligikaudu 16% juures; Serial Monitori käsk `g` tekitab 60 sekundiks ligikaudu 82% gaasianomaalia.

Väärtus on teadlikult **suhteline signaal, mitte ppm**. Rakendus märgib ebatavaliseks üle 70% taseme või vähemalt 20 protsendipunkti suuruse kiire muutuse. Piirid on `.env` failis `GAS_WARNING_PCT` ja `GAS_SPIKE_PCT`; need otsustab rakendus, mitte keelemudel.

## ESP32 pärisanduri versioon

Kataloogi `firmware/ruumiandur_esp32` sketch loeb tüüpilise MQ-2 mooduli `A0` väljundit ESP32 GPIO34 ehk ADC1 kaudu. Sama JSON-leping jääb alles; pärispakett sisaldab `gas_source: "mq2"`, `gas_warmup` olekut ja `simulated: false`. Mooduli kuni 5 V analoogväljundit ei tohi otse ESP32 sisendiga ühendada: kasuta pingejagurit või sobivat nivoonihutit. Konkreetne ühendus ja kalibreerimine on kirjeldatud sketch'i kõrval olevas README-s. `D0` komparaatoriväljundit see versioon ei kasuta.

MQ-2 on mitteselektiivne tuleohtliku gaasi ja suitsu pooljuhtandur. Winseni andmeleht määrab küttepingeks 5,0 V, küttevõimsuseks kuni 950 mW, mõõtevahemikuks 300–10 000 ppm tuleohtlikku gaasi standardtingimustel ja esmaseks eelsoojenduseks vähemalt 48 tundi. Ilma konkreetse gaasi, koormustakisti ja puhta õhu kalibreerimiseta ei teisendata ADC väärtust ppm-iks.

See prototüüp ei ole sertifitseeritud gaasi-, CO- ega suitsualarm ja seda ei tohi kasutada ohutusseadme asendajana.

Allikad: [Winsen MQ-2 juhend](https://www.winsen-sensor.com/d/files/newpdf/mq-2-%28ver1_6%29---manual.pdf) ja [Espressifi ESP32 ADC juhend](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32/schematic-checklist.html#adc).
