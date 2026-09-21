## Self-service WMS en Kaartlagen

Welkom bij de repository Self-service WMS en Kaartlagen.

Deze tool ondersteunt teams binnen de Gemeente Amsterdam bij twee dingen:

1. **Een kaartlaag aanvragen op [data.amsterdam.nl](https://data.amsterdam.nl).**
   Je doorloopt een formulier waarin je aangeeft onder welke collectie en sublaag de
   kaartlaag hoort, welke gegevens er op de detailpagina komen, en of de laag
   activeerbaar en publiek toegankelijk moet zijn. Het resultaat is een
   aanvraagbestand in JSON dat je meestuurt met je verzoek aan Team GEO.

2. **Een [WMS](https://mapserver.org/ogc/wms_server.html#wms-server) genereren**
   in de vorm van een MapFile voor MapServer. Dat is nodig om de kaartlaag te
   kunnen publiceren, maar je kunt de tool ook alleen hiervoor gebruiken, zonder
   aanvraag voor data.amsterdam.nl.

Welke van de twee je wilt, kies je op de eerste pagina. Kies je "alleen een WMS
maken", dan worden de publicatievragen overgeslagen.

Gegevens over de dataset worden automatisch opgehaald uit het
[Amsterdams Schema](https://github.com/Amsterdam/amsterdam-schema) en de
[DSO API](https://api.data.amsterdam.nl/v1/docs/). Je vult één link naar de
tabeldefinitie in; het thema, de geometriekolom, het geometrietype, de
attributen en het coördinaatstelsel volgen daaruit.

Op dit moment ondersteunt de tool alleen zogenaamde "simpele" MapFiles.

### Wat is een Simpele WMS?

Een simpele WMS voldoet aan de volgende kenmerken:

- Data wordt rechtstreeks opgehaald uit de Ref.DB zonder transformaties.
- Filtering is beperkt tot één kolom:
  - Voor één enkele kaartlaag, **of**
  - Voor meerdere categorieën binnen een kaartlaag.
- Eén kleur wordt gebruikt voor polygonen of symbolen.
- Geen complexe symbolen of kleurcombinaties.
- Geen verschillen in weergave op verschillende zoomniveaus.
- Geen combinatie van verschillende laagtypen in één MapFile (bijvoorbeeld punten
  en polygonen, of gewichten en locaties).
- Labels zijn eenvoudig en worden niet gegenereerd uit complexe queries.
- De data waarvoor een WMS wordt gegenereerd, moet "openbaar" zijn. In het
  [Amsterdamse schema](https://github.com/Amsterdam/amsterdam-schema) is de
  autorisatie gedefinieerd op dataset-, tabel- en attribuutniveau. Alleen data met
  het autorisatieniveau **openbaar** wordt door deze tool geaccepteerd.

### Hoe werkt het?

De applicatie draait in een Docker-container. Je hebt verder niets nodig: geen
Python-installatie en geen database.

1. Maak een lokale clone van deze repository:

   ```
   git clone https://github.com/Amsterdam/self-service-WMS.git
   ```

2. Navigeer naar de lokale map van de repository in je terminal.

3. Bouw en start de container:

   ```
   docker compose up --build -d
   ```

4. Open de applicatie op [http://localhost:5000](http://localhost:5000)

Meekijken in de logs, of stoppen:

```
docker compose logs -f
docker compose down
```

Na een codewijziging opnieuw bouwen met `docker compose up --build -d`.

Uitgebreidere instructies, waaronder het instellen van een `SECRET_KEY` en het
werken achter een netwerkproxy, staan in [DOCKER.md](DOCKER.md).

### Lokaal draaien zonder Docker

Voor ontwikkelwerk kun je de app ook direct starten:

```
pip install -r requirements.txt
python app.py
```

De app is dan bereikbaar op [http://127.0.0.1:5000](http://127.0.0.1:5000).

> Op Windows met meerdere Python-versies wijzen `pip` en `py` soms naar
> verschillende installaties. Gebruik in dat geval `py -m pip install -r
> requirements.txt` en `py app.py`, zodat het zeker dezelfde Python is.

### Technische opzet

De applicatie is bewust eenvoudig gehouden, zonder JavaScript-framework en zonder
build-stap.

**Backend.** Een Flask-applicatie (`app.py`), in productie geserveerd door
gunicorn. Flask rendert de pagina's en biedt een aantal JSON-endpoints. De browser
praat nooit rechtstreeks met GitHub of de DSO API: dat verloopt via de server, die
alleen verzoeken naar vaste, toegestane adressen doorlaat.

| Endpoint | Waarvoor |
|---|---|
| `/api/fetch-data` | Dataset- en tabelgegevens uit het Amsterdams Schema |
| `/api/collecties` | Bestaande collecties uit het kaartlagen-register |
| `/api/sublagen` | Bestaande sublagen binnen een collectie |
| `/api/fetch-columns` | Kolomnamen voor filter en label, uit de DSO API |
| `/api/generate-mapfile` | Een nieuwe MapFile |
| `/api/add-layer` | Een laag toevoegen aan een bestaande MapFile |
| `/api/replace-layer` | Een bestaande laag vervangen |
| `/healthz` | Healthcheck voor Docker en loadbalancers |

**Frontend.** Server-side gerenderde Jinja2-templates met gewone HTML, CSS en
vanilla JavaScript. Alle pagina's erven van `templates/base.html`, dat de header,
de huisstijl en de gedeelde opmaak bevat. De huisstijlkleuren staan als
CSS-variabelen (`--red`, `--ink`, enzovoort) in dat bestand. Dynamische gegevens
worden met `fetch` bij de endpoints hierboven opgehaald.

**Opmaak.** De lettertypen DM Sans en DM Mono komen van Google Fonts, iconen zijn
inline SVG, en het logo staat in `static/logo_amsterdam.svg`. De syntaxkleuring
van de MapFile is een handvol reguliere expressies, geen externe bibliotheek.

**Opbouw van de repository**

```
app.py                     Flask-applicatie en API-endpoints
requirements.txt           Python-afhankelijkheden
Dockerfile                 Containerdefinitie
docker-compose.yml         Lokaal draaien met Docker
static/
  logo_amsterdam.svg
templates/
  base.html                Gedeelde opmaak, header en huisstijl
  intro.html               Startpagina: publiceren of alleen een WMS
  pub_schema.html          Link naar de tabeldefinitie en gegevens ophalen
  pub_kaartlaag.html       Collectie, sublaag en kaartlaagnaam
  pub_eigenschappen.html   Detailpagina, activeerbaarheid en publieke toegang
  pub_samenvatting.html    Controle van de publicatie-aanvraag
  scenario1.html           WMS stap 1: MapFile-naam en groepsnaam
  scenario2.html           WMS stap 2: externe bronnen
  scenario3.html           WMS stap 3: filter, kleur en label
  scenario4.html           WMS stap 4 en 5: MapFile, aanvraag en downloads
```

De `pub_`-templates vormen het publicatiedeel, de `scenario`-templates het
WMS-deel. Kiest de gebruiker op de startpagina "alleen een WMS maken", dan gaat hij
direct naar `scenario1.html`.

**Doorontwikkeling.** Iedereen die HTML en wat JavaScript kent, kan een template
openen en aanpassen, zonder Node-toolchain. Het nadeel is dat sommige templates
lang zijn geworden, vooral `scenario4.html`. Groeit de tool verder, dan is het
uitsplitsen van de JavaScript naar losse bestanden in `static/` de eerste logische
stap, nog voordat een framework in beeld komt.

### Waar de gegevens blijven

De applicatie bewaart niets aan de serverkant. Er is geen database nodig, ook geen
SQLite:

- Dataset- en tabelgegevens komen live uit het Amsterdams Schema op GitHub.
- Collecties en sublagen komen live uit het kaartlagen-register in de DSO API.
- Je voortgang door het formulier staat in `sessionStorage` in je browser.
- De MapFile en het aanvraagbestand worden in je browser gedownload.

De enige serverstatus is een cache van vijftien minuten voor de collectielijst.

Dat betekent ook: sluit je het tabblad halverwege, dan is je invoer weg. En de
container kan zonder verlies herstart of opgeschaald worden.

### Uitgaand netwerkverkeer

De applicatie moet deze hosts over HTTPS kunnen bereiken:

| Host | Waarvoor |
|---|---|
| `raw.githubusercontent.com` | Amsterdams Schema, dataset- en tabeldefinities |
| `api.data.amsterdam.nl` | DSO API, kaartlagen-register, geometrietype |

Lukt dat niet, dan blijven de collectie- en sublaaglijsten leeg en moet je die
namen handmatig als "nieuw" opgeven. In [DOCKER.md](DOCKER.md) staat hoe je dit
vanuit de container test en hoe je een proxy instelt.
