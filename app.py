import re
import logging
import traceback
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify, session
import requests
import json

# ──────────────────────────────────────────────
# Logging configuratie (server-side only)
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# SSRF bescherming: toegestane domeinen
# ──────────────────────────────────────────────
ALLOWED_DOMAINS = {
    "raw.githubusercontent.com",   # Amsterdam Schema (GitHub raw)
    "api.data.amsterdam.nl",        # DSO API
}

GITHUB_RAW_BASE = "https://raw.githubusercontent.com"
DSO_API_BASE    = "https://api.data.amsterdam.nl"

def extract_github_path(url: str) -> str:
    """
    Trekt het pad uit een GitHub blob of raw URL en geeft een veilige
    raw.githubusercontent.com URL terug met hardcoded base.
    """
    url = url.strip()
    # GitHub blob → raw pad
    match = re.match(r"https?://github\.com/([^/]+/[^/]+)/blob/(.+)", url)
    if match:
        return f"{GITHUB_RAW_BASE}/{match.group(1)}/{match.group(2)}"
    # Al een raw URL — extraheer alleen het pad
    parsed = urlparse(url)
    if parsed.netloc == "raw.githubusercontent.com":
        return f"{GITHUB_RAW_BASE}{parsed.path}"
    raise ValueError(f"Ongeldige GitHub URL. Verwacht: github.com of raw.githubusercontent.com")

def extract_dso_path(url: str) -> str:
    """
    Trekt het pad uit een DSO API URL en geeft een veilige
    api.data.amsterdam.nl URL terug met hardcoded base.
    """
    url = url.strip()
    parsed = urlparse(url)
    if parsed.netloc not in ("api.data.amsterdam.nl", ""):
        raise ValueError(f"Ongeldige DSO API URL. Verwacht: api.data.amsterdam.nl")
    path = parsed.path
    if not path.startswith("/v1/"):
        raise ValueError("DSO API pad moet beginnen met /v1/")
    return f"{DSO_API_BASE}{path}"

app = Flask(__name__)
app.secret_key = "wms-secret-key-2024"

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.route("/")
def scenario1(): return render_template("scenario1.html")

@app.route("/scenario2")
def scenario2(): return render_template("scenario2.html")

@app.route("/scenario3")
def scenario3(): return render_template("scenario3.html")

@app.route("/scenario4")
def scenario4(): return render_template("scenario4.html")

def to_snake_case(name):
    if not name: return ""
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def is_openbaar(auth_val):
    return str(auth_val).upper() == "OPENBAAR"

# ──────────────────────────────────────────────
# API: Data ophalen (Fix voor SSRF & Exposure)
# ──────────────────────────────────────────────

@app.route("/api/fetch-data", methods=["POST"])
def fetch_data():
    try:
        data = request.json
        # Directe validatie van de variabelen die in requests.get gaan
        # url_dataset = validate_url(to_raw_url(data.get("url_dataset", "")))
        # url_tabel   = validate_url(to_raw_url(data.get("url_tabel", "")))
        url_dataset = extract_github_path(data.get("url_dataset", ""))
        url_tabel   = extract_github_path(data.get("url_tabel", ""))

        # ── 1. Dataset metadata ───────────────────────────────────────────
        resp_ds = requests.get(url_dataset, timeout=10)
        resp_ds.raise_for_status() # Best practice: check status
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
                "auth_error": True, "auth_niveau": "dataset",
                "auth_melding": "Deze dataset is niet openbaar beschikbaar.",
                "auth_waarde": ds_auth, "auth_reden": ds_json.get("reasonsNonPublic", []),
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
                "auth_error": True, "auth_niveau": "tabel",
                "auth_melding": "Deze tabel is niet openbaar beschikbaar.",
                "auth_waarde": tab_auth, "auth_reden": tab_json.get("reasonsNonPublic", []),
            })

        # ── 3. Tabelnaam & Geometrie ──────────────────────────────────────
        full_table_name = f"{to_snake_case(dataset_id)}_{to_snake_case(tabel_id)}_v{major_version}"
        schema_obj = tab_json.get("schema", {})
        main_geo   = schema_obj.get("mainGeometry", tab_json.get("mainGeometry", "geometrie"))

        geo_type = "POLYGON"
        props = schema_obj.get("properties", {})
        geom_prop = props.get(main_geo, {})
        format_val = str(geom_prop.get("$ref", geom_prop.get("format", ""))).lower()
        if "point" in format_val: geo_type = "POINT"
        elif "multipolygon" in format_val: geo_type = "MULTIPOLYGON"
        elif "multipoint" in format_val: geo_type = "MULTIPOINT"
        elif "line" in format_val or "linestring" in format_val: geo_type = "LINESTRING"

        # ── 4. Attribuut Check ───────────────────────────────────────────
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

    except ValueError:
       logger.warning("Validatiefout: %s", traceback.format_exc())
       return jsonify({"error": "Ongeldige invoer."}), 400
    except Exception:
        # Fix voor Information Exposure: Geen str(e) naar de gebruiker
        logger.error("Fout in fetch-data: %s", traceback.format_exc())
        return jsonify({"error": "Er is een interne fout opgetreden bij het ophalen van data."}), 500

# ──────────────────────────────────────────────
# API: Kolomnamen (Fix voor SSRF alert #6)
# ──────────────────────────────────────────────

@app.route("/api/fetch-columns", methods=["POST"])
def fetch_columns():
    try:
        data = request.json
        url_api_raw = data.get("url_api", "").strip()
        if not url_api_raw:
            return jsonify({"error": "Geen API URL opgegeven"}), 400
        
        # 1. Valideer de URL
        # url_api = validate_url(url_api_raw)
        url_api = extract_dso_path(url_api_raw)

        # 2. FIX: Gebruik 'params' in plaats van handmatige string-concatenatie (+)
        # Dit lost de Critical Alert op regel 238 in de PDF op.
        dso_headers = {"Accept": "application/hal+json, application/json;q=0.9, */*;q=0.8"}
        query_params = {"_pageSize": "1"}
        
        resp = requests.get(url_api, headers=dso_headers, params=query_params, timeout=15)
        resp.raise_for_status()
        api_data = resp.json()

        kolommen = []
        embedded = api_data.get("_embedded", {})
        candidates = list(embedded.values()) if embedded else [api_data.get("results", [])]
        for items in candidates:
            if isinstance(items, list) and items:
                kolommen = [k for k in items[0].keys() if not k.startswith("_") and k not in ("geometry", "geometrie", "type")]
                break

        return jsonify({"kolommen": kolommen})

#    except ValueError as e:
#        return jsonify({"error": str(e)}), 400
    except ValueError:
       logger.warning("Validatiefout: %s", traceback.format_exc())
       return jsonify({"error": "Ongeldige invoer."}), 400
    except Exception:
        logger.error("Fout in fetch-columns: %s", traceback.format_exc())
        return jsonify({"error": "Fout bij ophalen van kolomnamen."}), 500

# ──────────────────────────────────────────────
# API: MapFile Genereren
# ──────────────────────────────────────────────

@app.route("/api/generate-mapfile", methods=["POST"])
def generate_mapfile():
    data = request.json
    publisher      = data.get("publisher", "Team Datamanagement")
    group_name     = data.get("wms_groepsnaam", "mijn_groep")
    layer_name     = data.get("wms_laagnaam", "mijn_laag")
    description    = data.get("description", "")
    auth           = data.get("auth", "openbaar")
    tn             = data.get("table_name", "tabel_onbekend").replace("public.", "")
    gc             = data.get("mainGeometry", "geometrie")
    gt             = data.get("geometryType", "POLYGON").upper()
    gml_geo        = "multipolygon" if gt == "POLYGON" else "point"
    color          = data.get("color", "#000000")
    uid            = data.get("unique_id", "id")
    lbl            = data.get("label_kolom", "")

    data_line = f'"{gc} FROM public.{tn} USING UNIQUE {uid} USING SRID=28992"'
    if data.get("filter_kolom") and data.get("filter_waarde"):
        data_line = f'"{gc} FROM public.{tn} USING UNIQUE {uid} USING SRID=28992 WHERE {data["filter_kolom"]} = \'{data["filter_waarde"]}\'"'

    is_polygon = gt in ("POLYGON", "MULTIPOLYGON")
    mapfile = f"""MAP
  NAME                      "{layer_name}"
  STATUS                    ON
  SIZE                      800 600
  EXTENT                    -7000 289000 300000 629000
  UNITS                     METERS
  SHAPEPATH                 "../data"
  IMAGECOLOR                255 255 255
  CONFIG "MS_ERRORFILE"     "/tmp/mapserver.log"
  INCLUDE                   "header.inc"
  WEB
    METADATA
      "team"                "{publisher}"
      "ows_title"           "{group_name}"
      "ows_abstract"        "{description}"
      "auth"                "{auth}"
    END
  END
  LAYER
    NAME                    "{layer_name}"
    GROUP                   "{group_name}"
    INCLUDE                 "connection/dataservices.inc"
    DATA                    {data_line}
    TYPE                    {gt}
    TEMPLATE                "empty"
    PROJECTION
      "init=epsg:28992"
    END
    METADATA
      "ows_title"           "{layer_name.capitalize()}"
      "ows_abstract"        "{description}"
      "wms_group_title"     "{group_name}"
      "gml_featureid"       "{uid}"
      "gml_geometries"      "geometry"
      "gml_geometry_type"   "{gml_geo}"
      "gml_include_items"   "all"
      "gml_types"           "auto"
      "wms_include_items"   "all"
    END
    CLASS
      NAME                  "{layer_name}"
      TITLE                 "{layer_name.capitalize()}"
      STYLE
        ANTIALIAS           true
        COLOR               "{color}"{"\n        OPACITY             20" if is_polygon else ""}
      END
      STYLE
        OUTLINECOLOR        "{color}"
        WIDTH               2
      END{"\n    LABEL\n      ANGLE AUTO\n      COLOR 0 0 0\n      FONT \"ubuntu\"\n      TYPE truetype\n      SIZE 10\n      POSITION AUTO\n      PARTIALS FALSE\n      TEXT ([" + lbl + "])\n    END" if lbl else ""}
    END
  END
END"""
    return jsonify({"mapfile": mapfile.lstrip()})

if __name__ == "__main__":
    # Fix voor Debug Mode alert: debug=False
    app.run(debug=False, port=5000)