FROM python:3.12-slim

# Geen .pyc-bestanden, ongebufferde logs zodat "docker logs" meteen iets toont
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Eerst alleen requirements kopiëren: de pip-laag blijft gecached
# zolang de dependencies niet wijzigen
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ ./templates/
COPY static/ ./static/

# Niet als root draaien
RUN useradd --create-home --shell /usr/sbin/nologin wmsapp \
    && chown -R wmsapp:wmsapp /app
USER wmsapp

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=4)"

# Gunicorn in plaats van de Flask-ontwikkelserver.
# 3 workers met 2 threads: ruim genoeg voor een intern formulier dat
# vooral op externe API's wacht. De timeout staat hoog omdat het ophalen
# van de collectielijst meerdere pagina's langsgaat.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", \
     "--workers", "3", "--threads", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "app:app"]
