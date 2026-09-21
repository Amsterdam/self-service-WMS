# Self-service WMS en Kaartlagen in Docker

## Geen database nodig

De applicatie bewaart niets aan de serverkant:

- Dataset- en tabelgegevens komen live uit het Amsterdams Schema op GitHub
- Collecties en sublagen komen live uit het kaartlagen-register (DSO API)
- De voortgang van de gebruiker staat in `sessionStorage` in de browser
- De MapFile en het aanvraagbestand worden in de browser gedownload

Er is dus **geen SQLite en geen databaseserver** nodig. De enige serverstatus is
een cache in het geheugen van 15 minuten voor de collectielijst. Gaat de container
omlaag, dan is er niets verloren behalve die cache.

Gevolg: de container is stateless en je kunt er zonder meer meerdere van draaien
achter een loadbalancer. Er zijn geen volumes nodig.

## Starten

```bash
# Geheime sleutel aanmaken
python -c "import secrets; print(secrets.token_hex(32))"

# In een .env zetten naast docker-compose.yml
echo "SECRET_KEY=<de gegenereerde waarde>" > .env

docker compose up --build -d
docker compose logs -f
```

De app is dan bereikbaar op http://localhost:5000

Zonder compose:

```bash
docker build -t self-service-wms .
docker run -d -p 5000:5000 \
  -e SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" \
  --name self-service-wms self-service-wms
```

## Uitgaand netwerkverkeer

Dit is het enige dat in de praktijk misgaat. De container moet deze hosts over
HTTPS kunnen bereiken:

| Host | Waarvoor |
|---|---|
| `raw.githubusercontent.com` | Amsterdams Schema, dataset- en tabeldefinities |
| `api.data.amsterdam.nl` | DSO API, kaartlagen-register, geometrietype |
| `fonts.googleapis.com`, `fonts.gstatic.com` | Het lettertype DM Sans (door de browser, niet door de container) |

Loopt uitgaand verkeer via een proxy, zet dan `HTTP_PROXY` en `HTTPS_PROXY` in
`docker-compose.yml`. De `requests`-library pikt die variabelen automatisch op.

Controleren vanuit de container:

```bash
docker compose exec wms python -c \
  "import requests; print(requests.get('https://api.data.amsterdam.nl/v1/geo_services/wms_kaartlagen?_pageSize=1', timeout=15).status_code)"
```

Komt daar geen 200 uit, dan blijven de collectie- en sublaaglijsten leeg en moet
de gebruiker alles als "nieuw" opgeven.

## Wat er in de image zit

- `python:3.12-slim` als basis
- Flask, requests en gunicorn; geen systeempakketten extra nodig
- Gunicorn met 3 workers en 2 threads. De app wacht vooral op externe API's,
  dus threads helpen meer dan extra workers
- Draait als gebruiker `wmsapp`, niet als root
- Read-only rootfs met een tmpfs voor `/tmp`
- `HEALTHCHECK` op `/healthz`

Let op: elke gunicorn-worker heeft zijn eigen geheugencache. Met 3 workers wordt
de collectielijst dus tot 3 keer opgehaald in plaats van 1 keer. Dat is geen
probleem bij dit gebruiksvolume. Wil je dat later toch delen, dan is Redis de
logische stap — maar voeg dat niet toe zolang het niet nodig is.

## Omgevingsvariabelen

| Variabele | Verplicht | Waarvoor |
|---|---|---|
| `SECRET_KEY` | in productie | Flask-sleutel. Zonder deze variabele wordt bij elke start een willekeurige gegenereerd |
| `HTTP_PROXY` / `HTTPS_PROXY` | soms | Uitgaand verkeer via de netwerkproxy |
| `PORT` / `HOST` | nee | Alleen van belang als je `python app.py` gebruikt in plaats van gunicorn |

## Achter een reverse proxy

Draait de app achter nginx of een ingress op een ander pad of domein, geef dan de
gebruikelijke headers door (`X-Forwarded-For`, `X-Forwarded-Proto`) en start
gunicorn met `--forwarded-allow-ips`. De app maakt zelf geen absolute URL's aan,
dus verder is er niets aan te passen.
