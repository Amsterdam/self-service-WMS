import re
from flask import Flask, render_template, request, jsonify, session
import requests
import json
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = "wms-secret-key-2024"

# ──────────────────────────────────────────────
# Beveiliging: SSRF Allowlist
# ──────────────────────────────────────────────
# Alleen URL's van deze domeinen worden geaccepteerd door de server.
ALLOWED_DOMAINS = [
    "github.com", 
    "raw.githubusercontent.com", 
    "api.data.amsterdam.nl", 
    "data.amsterdam.nl"
]

def validate_url(url):
    """
    Controleert of de URL veilig is om aan te roepen vanaf de server.
    Voorkomt Server-Side Request Forgery (SSRF).
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        # Check of het protocol http(s) is en of het domein in onze lijst staat
        return parsed.scheme in ('http', 'https') and parsed.netloc in ALLOWED_DOMAINS
    except Exception:
        return False

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.route("/")
def scenario1():
    return render_template("scenario1.html")

@app.route("/scenario2")
def scenario2():
    return render_template("scenario2.html")

@app.route("/scenario3")
def scenario3():
    return render_template("scenario3.html")

@app.route("/scenario4")
def scenario4():
    return render_template("scenario4.html")

# ──────────────────────────────────────────────
# Hulpfuncties
# ──────────────────────────────────────────────

def to_raw_url(url):
    url = url.strip()
    match = re.match(r"https?://github\.com/([^/]+/[^/]+)/blob/(.+)", url)
    if match:
        return f"https://raw.githubusercontent.com/{match.group(1)}/{match.group(2)}"
    return url

def to_snake_case(name):
    if not name:
        return ""
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def is_openbaar(auth_val):
    return str(auth_val).upper() == "OPENBAAR"

# ──────────────────────────────────────────────
# API: Data ophalen (Stap 1 & 2)
# ──────────────────────────────────────────────

@app.route("/api/fetch-data", methods=["POST"])
def fetch_data():
    try:
        data = request.json
        url_dataset = to_raw_url(data.get("url_dataset", ""))
        url_tabel   = to_raw_url(data.get("url_tabel", ""))

        # --- SSRF VALIDATIE ---
        if not validate_url(url_dataset) or not validate_url(url_tabel):
            return jsonify({
                "error": "Onveilige URL gedetecteerd. Alleen Amsterdam.nl en GitHub domeinen zijn toegestaan."
            }), 403

        # ── 1. Dataset metadata ───────────────────────────────────────────
        resp_ds = requests.get(url_dataset, timeout=10)
        resp_ds.raise_for_status()
        ds_json = resp_ds.json()

        raw_publisher = ds_json.get("publisher", "/publishers/onbekend")
        if isinstance(raw_publisher, dict):
            raw_publisher = raw_publisher.get("$ref", "/publishers/onbekend")
        
        team_name   = raw_publisher.split("/")[-1]
        dataset_id  = ds_json.get("id", "dataset")
        description = ds_json.get("description", "")
        ds_auth     = ds_json.get("auth", "OPENBAAR")

        if not is_openbaar(ds_auth):
            return jsonify({
                "auth_error": True,
                "auth_niveau": "dataset",
                "auth_melding": "Deze dataset is niet openbaar beschikbaar.",
                "auth_waarde":  ds_auth,
                "auth_reden":   ds_json.get("reasonsNonPublic", []),
            })

        # ── 2. Tabel metadata ─────────────────────────────────────────────
        resp_tab = requests.get(url_tabel, timeout=10)
        resp_tab.raise_for_status()
        tab_json = resp_tab.json()

        tabel_id      = tab_json.get("id", "tabel")
        version_raw   = tab_json.get("version", "1.0.0")
        major_version = version_raw.split(".")[0]
        tab_auth      = tab_json.get("auth", "OPENBAAR")

        if not is_openbaar(tab_auth):
            return jsonify({
                "auth_error": True,
                "auth_niveau": "tabel",
                "auth_melding": "Deze tabel is niet openbaar beschikbaar.",
                "auth_waarde":  tab_auth,
                "auth_reden":   tab_json.get("reasonsNonPublic", []),
            })

        # ── 3. Tabelnaam opbouwen ────────────────────────────────────────