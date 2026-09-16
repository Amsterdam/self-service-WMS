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
