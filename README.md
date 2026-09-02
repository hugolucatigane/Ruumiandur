# Ruumiandur

Ühe tööpäeva prototüüp: andur saadab ruumi mõõtmised HTTP-ga FastAPI teenusesse, SQLite salvestab need, veebivaade näitab viimaseid väärtusi ning `/api/summary` koostab eestikeelse kokkuvõtte.

## Käivitamine

Vajalik on Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Veebivaade asub aadressil `http://127.0.0.1:8000` ja REST API dokumentatsioon aadressil `http://127.0.0.1:8000/docs`. Ilma riistvarata käivita teises terminalis andmesaatja ja testid:

```powershell
.\.venv\Scripts\python.exe tools\demo_sender.py --include-junk
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Seejärel vali veebivaates `ESP8266 · simulaator`, sest vaikimisi on valitud ESP32.

### AI ühendamine

AI saab ühendada kahel viisil. Kohaliku variandi jaoks paigalda ja käivita [Ollama](https://ollama.com), laadi mudel käsuga `ollama pull qwen3:8b` ning määra `.env` failis:

```dotenv
AI_PROVIDER=ollama
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:8b
```

OpenAI kasutamiseks loo [API võti](https://platform.openai.com/api-keys) ning määra samas failis:

```dotenv
AI_PROVIDER=openai
OPENAI_MODEL=gpt-5.6-luna
OPENAI_API_KEY=siia_oma_võti
```

API võtit ei tohi koodi ega Git-reposse lisada; `.env` on `.gitignore` failis. `AI_PROVIDER=auto` proovib esmalt Ollamat, seejärel API võtit ja kasutab mõlema puudumisel reeglipõhist kokkuvõtet.

ESP8266 simulaator asub failis `firmware/ruumiandur/ruumiandur.ino`. Pärisanduri variant kasutab ESP32, DHT22 ja MQ-2 andureid; ühendamine, Wokwi simulatsioon ja käivitamine on kirjeldatud failis [firmware/ruumiandur_esp32/README.md](firmware/ruumiandur_esp32/README.md). Mõlemad saadavad iga 10 sekundi järel sama JSON-lepingu järgi `POST /api/readings`; pärisandur kasutab väärtusi `simulated: false` ja `gas_source: "mq2"`.

## Katse ja tulemus

ESP8266 simuleerib temperatuuri, õhuniiskust ja MQ-2 suhtelist signaali. E2E-katse salvestas 15 kehtivat mõõtmist, lükkas 999 °C paketi vastusega HTTP 422 tagasi ning tuvastas 82,8% gaasitipu ja kiire muutuse. Lühikese andmestiku puhul märgib 24 tunni kokkuvõte katvuse ebapiisavaks ega väida, et kogu periood oli normaalne. Kõik 25 automaattesti läbivad; ESP8266, ESP32 ja Wokwi firmware variandid kompileeruvad.

## Otsused, piirangud ja riskid

Ebatavalisuse otsustab kood, mitte keelemudel. Prototüübi piirid on 20–25 °C, 40–60% RH, MQ-2 suhteline tase 70% ning kiired muutused vähemalt 3 °C või 20 protsendipunkti. Need on seadistatavad demoreeglid, mitte meditsiini- ega tuleohutuspiirid. Ainult piisava katvuse ja terve anduri korral saadetakse mudelile toorandmete asemel statistika, kuni kuus sündmust, anduri olek ja reeglipõhine mustand; nii on sisend väike ja mudel ei otsusta ise, mis on ohtlik.

Vigased paketid jäetakse statistikast välja. Üle 35 sekundi vaikinud andur märgitakse `offline`; piisavalt pika muutumatu väärtuse korral tekib kvaliteedihoiatus. Seadmel on umbes 20 minuti RAM-puhver, kuid see kaob voolukatkestusel. MQ-2 tulemus on kalibreerimata suhteline signaal, mitte ppm ning pärisandureid pole võrdlusmõõtjaga testitud. 1000 kasutaja korral muutuksid SQLite, ühe protsessi kirjutamine ja 5-sekundiline veebipolling pudelikaelaks. Puuduvad autentimine, TLS, seadmeprovisioneerimine ja monitooring.

## Järgmine samm ja välja jäetu

Järgmine samm on päris DHT22 ja MQ-2 võrdlus kalibreeritud mõõtjatega ning ühe nädala piloot. Selleks on vaja pärisandureid, võrdlusmõõtjat, valdkonnaomanikku piiride kinnitamiseks ja pilootkasutajaid. MQTT, pilvepaigaldus, tootmisandmebaas, püsimälupuhver, autentimine, konteinerid ja CI jäid ühe tööpäeva skoobist välja.

Arenduses kasutasin OpenAI Codexit koodi, testide ja dokumentatsiooni koostamiseks ning kohalikku Qwen3 mudelit kokkuvõtte kontrollimiseks. Codex pakkus alguses ESP32/Reacti-põhist põhilahendust; lihtsustasin selle ESP8266 simulaatoriks, FastAPI teenuseks ja vanilla veebivaateks. OpenAI API haru kontrollisin mock-testiga, mitte päris API võtmega.