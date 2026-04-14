import re
from flask import Flask, render_template, request, jsonify, session
import requests
import json
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = "wms-secret-key-2024"

# ──────────────────────────────────────────────
# Beveiliging: SSRF Allowlist & Validatie
# ──────────────────────────────────────────────
ALLOWED_DOMAINS = [
    "github.com", 
    "raw.githubusercontent.com", 
    "api.data.amsterdam.nl", 
    "data.amsterdam.nl"
]

def validate_url(url):
    """Controleert of de URL veilig is en tot de allowlist behoort."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme in ('http', 'https') and parsed.netloc in ALLOWED_DOMAINS
    except Exception:
        return False

# ──────────────────────────────────────────────
# Routes & Hulpfuncties
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

def to_raw_url(url):
    url = url.strip()
    match = re.match(r"https?://github\.com/([^/]+/[^/]+)/blob/(.+)", url)
    if match:
        return f"https://raw.githubusercontent.com/{match.group(1)}/{match.group(2)}"
    return url

def to_snake_case(name):
    if not name: return ""
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def is_openbaar(auth_val):
    return str(auth_val).upper() == "OPENBAAR"

# ──────────────────────────────────────────────
# API: Data ophalen (Met Inline SSRF Fix)
# ──────────────────────────────────────────────

@app.route("/api/fetch-data", methods=["POST"])
def fetch_data():
    try:
        data = request.json
        url_dataset_raw = to_raw_url(data.get("url_dataset", ""))
        url_tabel_raw   = to_raw_url(data.get("url_tabel", ""))

        # CodeQL Fix: Voer de requests alleen uit binnen dit validatie-block
        if validate_url(url_dataset_raw) and validate_url(url_tabel_raw):
            
            # 1. Dataset metadata
            resp_ds = requests.get(url_dataset_raw, timeout=10)
            resp_ds.raise_for_status()
            ds_json = resp_ds.json()

            # 2. Tabel metadata
            resp_tab = requests.get(url_tabel_raw, timeout=10)
            resp_tab.raise_for_status()
            tab_json = resp_tab.json()
            
        else:
            return jsonify({"error": "Onveilige URL gedetecteerd (SSRF-beveiliging)."}), 403

        # --- Verwerking Metadata ---
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
                "auth_melding": "Deze dataset is niet openbaar.",
                "auth_waarde": ds_auth,
                "auth_reden": ds_json.get("reasonsNonPublic", []),
            })

        tabel_id      = tab_json.get("id", "tabel")
        version_raw   = tab_json.get("version", "1.0.0")
        major_version = version_raw.split(".")[0]
        tab_auth      = tab_json.get("auth", "OPENBAAR")

        if not is_openbaar(tab_auth):
            return jsonify({
                "auth_error": True, "auth_niveau": "tabel",
                "auth_melding": "Deze tabel is niet openbaar.",
                "auth_waarde": tab_auth,
                "auth_reden": tab_json.get("reasonsNonPublic", []),
            })

        # --- Tabelnaam & Geometrie ---
        clean_ds        = to_snake_case(dataset_id)
        clean_tab       = to_snake_case(tabel_id)
        full_table_name = f"{clean_ds}_{clean_tab}_v{major_version}"

        schema_obj = tab_json.get("schema", {})
        main_geo   = schema_obj.get("mainGeometry", tab_json.get("mainGeometry", "geometrie"))

        geo_type = "POLYGON"
        props     = schema_obj.get("properties", {})
        geom_prop = props.get(main_geo, {})
        format_val = str(geom_prop.get("$ref", geom_prop.get("format", ""))).lower()
        
        if "point" in format_val: geo_type = "POINT"
        elif "multipolygon" in format_val: geo_type = "MULTIPOLYGON"
        elif "multipoint" in format_val: geo_type = "MULTIPOINT"
        elif "line" in format_val or "linestring" in format_val: geo_type = "LINESTRING"

        # --- Attribuut Check ---
        niet_openbaar_attribuut = None
        for attr_naam, attr_def in props.items():
            if not is_openbaar(attr_def.get("auth", "OPENBAAR")):
                niet_openbaar_attribuut = {"naam": attr_naam, "auth": attr_def.get("auth"), "reden": attr_def.get("reasonsNonPublic", [])}
                break

        if niet_openbaar_attribuut:
            return jsonify({
                "auth_error": True, "auth_niveau": "attribuut",
                "auth_melding": f"Kolom '{niet_openbaar_attribuut['naam']}' is niet openbaar.",
                "auth_waarde": niet_openbaar_attribuut["auth"],
                "auth_reden": niet_openbaar_attribuut["reden"],
                "auth_kolom": niet_openbaar_attribuut["naam"],
            })

        unique_id = next((r for r in schema_obj.get("required", []) if r != "schema"), "id")

        return jsonify({
            "publisher": team_name, "description": description, "table_name": full_table_name,
            "mainGeometry": main_geo, "geometryType": geo_type, "auth": ds_auth, "unique_id": unique_id,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ──────────────────────────────────────────────
# API: Kolomnamen (Met Inline SSRF & Params Fix)
# ──────────────────────────────────────────────

@app.route("/api/fetch-columns", methods=["POST"])
def fetch_columns():
    try:
        data = request.json
        url_api_raw = data.get("url_api", "").strip()
        
        if not url_api_raw:
            return jsonify({"error": "Geen API URL opgegeven"}), 400

        # SSRF FIX: Inline validatie + params object
        if validate_url(url_api_raw):
            dso_headers = {"Accept": "application/hal+json, application/json;q=0.9, */*;q=0.8"}
            query_params = {"_pageSize": "1"}
            
            resp = requests.get(url_api_raw, headers=dso_headers, params=query_params, timeout=15)
            resp.raise_for_status()
            api_data = resp.json()
        else:
            return jsonify({"error": "Niet toegestane API URL."}), 403

        kolommen = []
        embedded = api_data.get("_embedded", {})
        candidates = list(embedded.values()) if embedded else [api_data.get("results", [])]
        for items in candidates:
            if isinstance(items, list) and items:
                feature = items[0]
                kolommen = [k for k in feature.keys() if not k.startswith("_") and k not in ("geometry", "geometrie", "type")]
                break

        return jsonify({"kolommen": kolommen})

    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ──────────────────────────────────────────────
# API: MapFile Genereren
# ──────────────────────────────────────────────

@app.route("/api/generate-mapfile", methods=["POST"])
def generate_mapfile():
    data = request.json
    # ... (Onveranderd, aangezien hier geen externe requests worden gedaan) ...
    p = data.get("publisher", "Team Datamanagement")
    gn = data.get("wms_groepsnaam", "mijn_groep")
    ln = data.get("wms_laagnaam", "mijn_laag")
    desc = data.get("description", "")
    auth = data.get("auth", "openbaar")
    tn = data.get("table_name", "tabel_onbekend").replace("public.", "")
    gc = data.get("mainGeometry", "geometrie")
    gt = data.get("geometryType", "POLYGON").upper()
    col = data.get("color", "#000000")
    uid = data.get("unique_id", "id")
    lbl = data.get("label_kolom", "")

    data_line = f'"{gc} FROM public.{tn} USING UNIQUE {uid} USING SRID=28992"'
    if data.get("filter_kolom") and data.get("filter_waarde"):
        data_line = f'"{gc} FROM public.{tn} USING UNIQUE {uid} USING SRID=28992 WHERE {data["filter_kolom"]} = \'{data["filter_waarde"]}\'"'

    is_poly = gt in ("POLYGON", "MULTIPOLYGON")
    
    mapfile = f"""MAP
  NAME "{ln}"
  STATUS ON
  EXTENT -7000 289000 300000 629000
  UNITS METERS
  CONFIG "MS_ERRORFILE" "/tmp/mapserver.log"
  INCLUDE "header.inc"
  WEB
    METADATA
      "team" "{p}"
      "ows_title" "{gn}"
      "ows_abstract" "{desc}"
      "auth" "{auth}"
    END
  END
  LAYER
    NAME "{ln}"
    GROUP "{gn}"
    INCLUDE "connection/dataservices.inc"
    DATA {data_line}
    TYPE {gt}
    METADATA
      "ows_title" "{ln.capitalize()}"
      "gml_featureid" "{uid}"
      "gml_include_items" "all"
    END
    CLASS
      NAME "{ln}"
      STYLE
        COLOR "{col}"{"\n        OPACITY 20" if is_poly else ""}
      END
      STYLE
        OUTLINECOLOR "{col}"
        WIDTH 2
      END{"\n    LABEL\n      TEXT ([" + lbl + "])\n    END" if lbl else ""}
    END
  END
END"""
    return jsonify({"mapfile": mapfile.lstrip()})

if __name__ == "__main__":
    app.run(debug=True, port=5000)