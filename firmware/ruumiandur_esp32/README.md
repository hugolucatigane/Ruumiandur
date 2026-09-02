# ESP32 + DHT22 + MQ-2 püsivara

See programm saadab simulaatoriga samas vormingus JSON-andmeid, kuid loeb päris andureid. Välja `gas_source` väärtus on `mq2`, välja `simulated` väärtus on `false` ja iga käivituse esimesed viis minutit on märgitud väljaga `gas_warmup: true`. API salvestab soojenemisperioodi mõõtmised, kuid jätab need gaasistatistikast ja hoiatustest välja.

## Ühendused (klassikaline ESP32 DevKit / WROOM)

| Andur | Anduri viik | ESP32 / toide |
| --- | --- | --- |
| DHT22 | VCC | 3,3 V |
| DHT22 | DATA | GPIO4, 4,7–10 kΩ tõmbetakistiga 3,3 V peale |
| DHT22 | GND | GND |
| MQ-2 moodul | VCC | Stabiliseeritud 5 V toide |
| MQ-2 moodul | GND | ESP32-ga ühine GND |
| MQ-2 moodul | A0 | GPIO34 allpool kirjeldatud pingejaguri kaudu |

MQ-2 küttekeha võib tarbida ligikaudu 150–200 mA. Ära toida seda ESP32 3,3 V viigust. Mooduli A0 väljund võib läheneda 5 voldile, kuid ESP32 GPIO-le ei tohi anda üle 3,3 V. Kasuta näiteks 10 kΩ takistit A0 ja GPIO34 vahel ning 15 kΩ takistit GPIO34 ja GND vahel; nii väheneb 5 V ligikaudu 3,0 voldini. Mõõda enne ühendamist oma mooduli tegelik maksimaalne väljundpinge. D0 viiku ei kasutata.

GPIO34 on valitud teadlikult, sest see kuulub ADC1 alla. Klassikalistel ESP32 plaatidel tekib ADC2 viikude kasutamisel konflikt Wi-Fi-ga.

## Kompileerimine ja seadmesse laadimine

1. Paigalda Arduino IDE-s `esp32 by Espressif Systems`.
2. Kopeeri `secrets.example.h` faili nimega `secrets.h` ning määra Wi-Fi andmed ja API aadress.
3. Ava `ruumiandur_esp32.ino` ja vali **ESP32 Dev Module** või oma täpne ESP32 plaat.
4. Laadi programm seadmesse ja ava jadamonitor kiirusel 115200 boodi.

Programm sisaldab oma väikest DHT22 protokolli lugejat, seega pole välist Arduino teeki vaja. Mõõtmine saadetakse iga 10 sekundi järel. Kui DHT22 kontrollsumma või ajastuse kontroll ebaõnnestub, jäetakse mõõtmine saatmata, mitte ei saadeta väljamõeldud väärtust.

Kui Wi-Fi või API pole kättesaadav, hoiab programm RAM-i ringpuhvris kuni 120 mõõtmist ehk vaikimisi intervalli korral umbes 20 minuti jagu andmeid. Ajutiste vigade järel proovitakse uuesti ning ühenduse taastumisel saadetakse järjekord vanimast mõõtmisest alates. Iga päring sisaldab seadme tööaega mõõtmise ja saatmise hetkel, mille järgi saab server taastada mõõtmise ligikaudse algse UTC-ajatempli. Taaskäivituse või voolukatkestuse korral läheb RAM-is olev järjekord kaotsi. Täis puhvrist eemaldatakse vanim mõõtmine.

Füüsilise seadme ID on `esp32-bedroom-1`. Sisesta see veebivaate väljale **Seade**. Simulaatori ID on `esp8266-bedroom-1`.

## MQ-2 kalibreerimine

`gas_level_pct` on suhteline 0–100% signaal, mitte gaasi kontsentratsioon ühikutes ppm. Vaikimisi teisendatakse ADC näidud 0–4095 otse vahemikku 0–100%. Pärast anduri esmast sissepõletamist ja stabiliseerumist mõõda väärtus puhtas õhus ning ohutult saadud võrdlusolukorras. Seejärel uuenda programmi alguses väärtusi `MQ2_REFERENCE_LOW_RAW` ja `MQ2_REFERENCE_HIGH_RAW`.

Viie minuti pikkune `gas_warmup` periood jätab analüüsist välja ainult tavapärase taaskäivituse järgse stabiliseerumise aja. See ei asenda anduri tootja nõutud esmast sissepõletamist. Projekt ei ole sertifitseeritud gaasi-, suitsu-, tulekahju- ega vingugaasialarm.

Peamised allikad: [Winseni MQ-2 juhend](https://www.winsen-sensor.com/d/files/newpdf/mq-2-%28ver1_6%29---manual.pdf), [Espressifi ESP32 ADC juhised](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32/schematic-checklist.html#adc) ja [ESP32 elektrilised piirväärtused](https://documentation.espressif.com/esp32_datasheet_en.html#electrical-characteristics).

## Wokwi simulatsioon

Kaust sisaldab täielikku kohalikku Wokwi projekti. `diagram.template.json` ühendab ESP32 DevKit v1 interaktiivsete DHT22 ja MQ-2 komponentidega. Kompileerimisskript loob käivitatava faili `diagram.json` ning `wokwi.toml` viitab kompileeritud simulatsiooni püsivarale.

1. Seadista `firmware/ruumiandur/secrets.h`. Selle faili `API_URL` väärtust kasutab ka Wokwi.
2. Käivita PowerShellis `./build-wokwi.ps1`. Skript loob Gitist eiratavad failid `secrets.wokwi.generated.h` ja `diagram.json`. Simulatsioon kasutab Wokwi sisseehitatud võrku `Wokwi-GUEST`, sest see ei näe sinu füüsilist Wi-Fi pääsupunkti.
3. Paigalda ja ava VS Code'is Wokwi laiendus. Laiendus sisaldab privaatset IoT-lüüsi, seega ei tohi projekt viidata eraldi `localhost:9011` lüüsile.
4. Ava see kaust ja käivita käsupaletist **Wokwi: Start Simulator**. Kui VS Code'is on avatud repositooriumi juurkaust, käivita esmalt **Wokwi: Select Config File** ja vali `firmware/ruumiandur_esp32/wokwi.toml`.
5. Simuleeritud väärtuste muutmiseks klõpsa diagrammil DHT22 või MQ-2 komponendil.

Simulatsioon ühendub võrku `Wokwi-GUEST`, saadab mõõtmised ühisele `API_URL`-ile, lühendab MQ-2 viieminutilise käivitusjärgse soojenemisaja 15 sekundile ja väljastab iga täieliku päringu jadamonitorile kujul `JSON {...}`. Päris ESP32 kasutab endiselt mõlemat Wi-Fi väärtust failist `firmware/ruumiandur/secrets.h`; ainult Wokwi asendab need oma nõutud virtuaalse pääsupunktiga. Wokwi avalik lüüs ei pääse kohalikule API-le ligi, seega sõltub kohalik andmete saatmine VS Code'i laienduse sisseehitatud privaatsest lüüsist.

Ära lisa faili `secrets.wokwi.generated.h` ega kausta `build/wokwi` Giti ning ära jaga neid, sest need sisaldavad või kasutavad seadistatud API aadressi. Repositooriumi `.gitignore` juba välistab need asukohad.
