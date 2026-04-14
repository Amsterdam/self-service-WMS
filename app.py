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
    # Verandert CamelCase naar snake_case
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def is_openbaar(auth_val):
    """Geeft True terug als de auth waarde openbaar is."""
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

        # ── 3. Tabelnaam opbouwen ─────────────────────────────────────────
        clean_ds        = to_snake_case(dataset_id)
        clean_tab       = to_snake_case(tabel_id)
        full_table_name = f"{clean_ds}_{clean_tab}_v{major_version}"

        # ── 4. Geometrie ──────────────────────────────────────────────────
        schema_obj = tab_json.get("schema", {})
        main_geo   = schema_obj.get("mainGeometry", tab_json.get("mainGeometry", "geometrie"))

        geo_type = "POLYGON"
        props     = schema_obj.get("properties", {})
        geom_prop = props.get(main_geo, {})
        format_val = str(geom_prop.get("$ref", geom_prop.get("format", ""))).lower()
        
        if "point" in format_val:
            geo_type = "POINT"
        elif "multipolygon" in format_val:
            geo_type = "MULTIPOLYGON"
        elif "multipoint" in format_val:
            geo_type = "MULTIPOINT"
        elif "line" in format_val or "linestring" in format_val:
            geo_type = "LINESTRING"

        # ── 5. Check 3: attribuut-niveau auth ────────────────────────────
        niet_openbaar_attribuut = None
        for attr_naam, attr_def in props.items():
            attr_auth = attr_def.get("auth", "OPENBAAR")
            if not is_openbaar(attr_auth):
                niet_openbaar_attribuut = {
                    "naam":   attr_naam,
                    "auth":   attr_auth,
                    "reden":  attr_def.get("reasonsNonPublic", []),
                }
                break

        if niet_openbaar_attribuut:
            return jsonify({
                "auth_error": True,
                "auth_niveau": "attribuut",
                "auth_melding": f"De tabel bevat niet-openbare kolom: '{niet_openbaar_attribuut['naam']}'.",
                "auth_waarde":  niet_openbaar_attribuut["auth"],
                "auth_reden":   niet_openbaar_attribuut["reden"],
                "auth_kolom":   niet_openbaar_attribuut["naam"],
            })

        required  = schema_obj.get("required", [])
        unique_id = next((r for r in required if r != "schema"), "id")

        return jsonify({
            "publisher":    team_name,
            "description":  description,
            "table_name":   full_table_name,
            "mainGeometry": main_geo,
            "geometryType": geo_type,
            "auth":         ds_auth,
            "unique_id":    unique_id,
        })

    except Exception as e:
        print(f"ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 400

# ──────────────────────────────────────────────
# API: Kolomnamen ophalen
# ──────────────────────────────────────────────

@app.route("/api/fetch-columns", methods=["POST"])
def fetch_columns():
    try:
        data    = request.json
        url_api = data.get("url_api", "").strip()
        
        if not url_api:
            return jsonify({"error": "Geen API URL opgegeven"}), 400

        # --- SSRF VALIDATIE ---
        if not validate_url(url_api):
            return jsonify({"error": "Onveilige API URL gedetecteerd."}), 403

        dso_headers = {
            "Accept": "application/hal+json, application/json;q=0.9, */*;q=0.8"
        }
        sep   = "&" if "?" in url_api else "?"
        resp  = requests.get(url_api + sep + "_pageSize=1", headers=dso_headers, timeout=15)
        resp.raise_for_status()
        api_data = resp.json()

        kolommen = []
        embedded = api_data.get("_embedded", {})
        candidates = list(embedded.values()) if embedded else [api_data.get("results", [])]
        for items in candidates:
            if isinstance(items, list) and items:
                feature = items[0]
                kolommen = [
                    k for k in feature.keys()
                    if not k.startswith("_")
                    and k not in ("geometry", "geometrie", "type")
                ]
                break

        return jsonify({"kolommen": kolommen})

    except Exception as e:
        print(f"ERROR fetch-columns: {str(e)}")
        return jsonify({"error": str(e)}), 400


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
    
    raw_table_name = data.get("table_name", "tabel_onbekend")
    table_name     = raw_table_name.replace("public.", "")
    
    geo_column     = data.get("mainGeometry", "geometrie")
    geo_type       = data.get("geometryType", "POLYGON").upper()
    gml_geo        = "multipolygon" if geo_type == "POLYGON" else "point"
    
    color          = data.get("color", "#000000")
    outline        = data.get("color", "#000000")
    filter_kolom   = data.get("filter_kolom", "")
    filter_waarde  = data.get("filter_waarde", "")
    label_kolom    = data.get("label_kolom", "")
    unique_id      = data.get("unique_id", "id")

    if filter_kolom and filter_waarde:
        data_line = f'"{geo_column} FROM public.{table_name} USING UNIQUE {unique_id} USING SRID=28992 WHERE {filter_kolom} = \'{filter_waarde}\'"'
    else:
        data_line = f'"{geo_column} FROM public.{table_name} USING UNIQUE {unique_id} USING SRID=28992"'

    is_polygon   = geo_type in ("POLYGON", "MULTIPOLYGON")
    
    # Mapfile string opbouw
    mapfile = f"""MAP
  NAME                     "{layer_name}"
  STATUS                   ON
  SIZE                     800 600
  EXTENT                   -7000 289000 300000 629000
  UNITS                    METERS
  SHAPEPATH                "../data"
  IMAGECOLOR               255 255 255
  CONFIG "MS_ERRORFILE"     "/tmp/mapserver.log"

  INCLUDE                  "header.inc"

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
    TYPE                    {geo_type}
    TEMPLATE                "empty"
    PROJECTION
      "init=epsg:28992"
    END

    METADATA
      "ows_title"           "{layer_name.capitalize()}"
      "ows_abstract"        "{description}"
      "wms_group_title"     "{group_name}"
      "gml_featureid"       "{unique_id}"
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
        OUTLINECOLOR        "{outline}"
        WIDTH               2
      END{"\n    LABEL\n      ANGLE         AUTO\n      COLOR         0 0 0\n      FONT          \"ubuntu\"\n      TYPE          truetype\n      SIZE          10\n      POSITION      AUTO\n      PARTIALS      FALSE\n      TEXT          (\"[" + label_kolom + "]\")" + "\n    END" if label_kolom else ""}
    END
  END

END"""

    return jsonify({"mapfile": mapfile.lstrip()})

if __name__ == "__main__":
    app.run(debug=True, port=5000)