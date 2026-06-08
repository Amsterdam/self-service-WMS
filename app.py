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
    # camelCase splitsen
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    s2 = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1)
    # letter→cijfer splitsing (bijv. amsterdam2025 → amsterdam_2025)
    # maar NIET na 'v' zodat v1/v2/v3 intact blijft
    s3 = re.sub(r'(?<=[a-mo-uw-z])(\d)', r'_\1', s2)
    # cijfer→letter (bijv. 2025v → 2025_v)
    s4 = re.sub(r'(\d)([a-zA-Z])', r'\1_\2', s3)
    return re.sub(r'_+', '_', s4).lower().strip('_')

def to_title_case(name: str) -> str:
    """Vervangt underscores door spaties en capitaliseert elk woord.
    bijv. canon_amsterdam → Canon Amsterdam"""
    return ' '.join(w.capitalize() for w in name.replace('_', ' ').split())


def is_openbaar(auth_val):
    return str(auth_val).upper() == "OPENBAAR"

# ──────────────────────────────────────────────
# API: Data ophalen (Fix voor SSRF & Exposure)
# ──────────────────────────────────────────────

@app.route("/api/fetch-data", methods=["POST"])
def fetch_data():
    try:
        data = request.json
        url_tabel_raw = data.get("url_tabel", "")
        url_tabel     = extract_github_path(url_tabel_raw)

        # Dataset URL afleiden als niet opgegeven:
        # .../datasets/amsterdam_canon/canonAmsterdam2025/v1.json
        #  → .../datasets/amsterdam_canon/dataset.json
        url_dataset_raw = data.get("url_dataset", "").strip()
        if not url_dataset_raw:
            m = re.match(
                r"(https?://github\.com/[^/]+/[^/]+/blob/[^/]+/datasets/[^/]+)/.*",
                url_tabel_raw.strip()
            )
            if m:
                url_dataset_raw = m.group(1) + "/dataset.json"
        url_dataset = extract_github_path(url_dataset_raw)

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
        props      = schema_obj.get("properties", {})

        # Stap 1: mainGeometry als expliciete sleutel (op schema- of tabel-niveau)
        main_geo = schema_obj.get("mainGeometry") or tab_json.get("mainGeometry")

        # Stap 2: als mainGeometry ontbreekt, zoek in properties naar geometrie-veld
        if not main_geo:
            GEO_KEYWORDS = ("geometry", "geometrie", "geom")
            for kolom_naam, kolom_def in props.items():
                if kolom_naam.lower() in GEO_KEYWORDS:
                    main_geo = kolom_naam
                    break
            # Stap 3: zoek via $ref of format op geo-type keywords
            if not main_geo:
                for kolom_naam, kolom_def in props.items():
                    ref_val = str(kolom_def.get("$ref", kolom_def.get("format", ""))).lower()
                    if any(kw in ref_val for kw in ("geojson", "polygon", "point", "linestring", "multipolygon")):
                        main_geo = kolom_naam
                        break
            if not main_geo:
                main_geo = "geometrie"  # laatste fallback

        # Geometrietype bepalen uit de $ref of format van het gevonden geometrieveld
        geo_type  = None
        geom_prop = props.get(main_geo, {})
        format_val = str(geom_prop.get("$ref", geom_prop.get("format", ""))).lower()

        # Alleen toewijzen als het een specifiek type is (niet generiek Geometry.json)
        if "multipolygon" in format_val:      geo_type = "MULTIPOLYGON"
        elif "multipoint" in format_val:      geo_type = "MULTIPOINT"
        elif "point" in format_val:           geo_type = "POINT"
        elif "multilinestring" in format_val: geo_type = "MULTILINESTRING"
        elif "linestring" in format_val or "line" in format_val: geo_type = "LINESTRING"
        elif "polygon" in format_val:         geo_type = "POLYGON"
        # "geometry.json" zonder specifiek type → geo_type blijft None → gebruik DSO API

        # ── DSO API: geometrietype ophalen als fallback ───────────────
        url_api = data.get("url_api", "").strip()
        if (not geo_type or geo_type == "POLYGON") and url_api:
            # Haal één feature op en lees het geometry.type veld
            try:
                dso_headers = {"Accept": "application/hal+json, application/json;q=0.9, */*;q=0.8"}
                url_api_safe = extract_dso_path(url_api)
                sep = "&" if "?" in url_api_safe else "?"
                r_api = requests.get(url_api_safe + sep + "_pageSize=1", headers=dso_headers, timeout=10)
                if r_api.ok:
                    api_data = r_api.json()
                    embedded = api_data.get("_embedded", {})
                    candidates = list(embedded.values()) if embedded else [api_data.get("results", [])]
                    for items in candidates:
                        if isinstance(items, list) and items:
                            feature = items[0]
                            for geo_key in ("geometry", "geometrie", main_geo):
                                geom = feature.get(geo_key)
                                if geom and isinstance(geom, dict) and geom.get("type"):
                                    geo_type = geom["type"].upper()
                                    break
                        if geo_type:
                            break
            except Exception:
                pass  # DSO API fallback mislukt — gebruik standaard POLYGON

        if not geo_type:
            geo_type = "POLYGON"  # laatste fallback

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
        crs       = ds_json.get("crs", "EPSG:28992")

        return jsonify({
            "publisher": team_name, "description": description, "table_name": full_table_name,
            "mainGeometry": main_geo, "geometryType": geo_type, "auth": ds_auth,
            "unique_id": unique_id, "crs": crs,
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
                # label = originele camelCase naam (zichtbaar voor gebruiker)
                # value = snake_case naam (PostgreSQL conventie, komt in MapFile)
                kolommen = [
                    {"label": k, "value": to_snake_case(k)}
                    for k in items[0].keys()
                    if not k.startswith("_") and k not in ("geometry", "geometrie", "type")
                ]
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
# Hulpfunctie: bouw één LAYER-blok
# ──────────────────────────────────────────────

def build_layer_block(d: dict) -> str:
    """Genereert één LAYER...END blok op basis van de payload."""
    group_name  = d.get("wms_groepsnaam", "mijn_groep")
    layer_name  = d.get("wms_laagnaam", "mijn_laag")
    description = d.get("description", "")
    tn          = d.get("table_name", "tabel_onbekend").replace("public.", "")
    gc          = d.get("mainGeometry", "geometrie")
    gt_raw      = d.get("geometryType", "POLYGON").upper()
    # MapServer TYPE kent alleen POLYGON, POINT, LINE — geen MULTI-varianten
    GT_MAP = {
        "MULTIPOLYGON":   "POLYGON",
        "MULTIPOINT":     "POINT",
        "MULTILINESTRING":"LINE",
        "LINESTRING":     "LINE",
    }
    gt          = GT_MAP.get(gt_raw, gt_raw)
    # gml_geometry_type wel de volledige naam (lowercase)
    gml_geo     = gt_raw.lower()
    color       = d.get("color", "#000000")
    uid         = d.get("unique_id", "id")
    lbl         = to_snake_case(d.get("label_kolom", ""))
    is_polygon  = gt == "POLYGON"
    is_point    = gt == "POINT"

    # wms_group_title: title_case van de groepsnaam (Fix 3)
    group_title = to_title_case(group_name)
    crs         = d.get("crs", "EPSG:28992")

    if d.get("filter_kolom") and d.get("filter_waarde"):
        fk = to_snake_case(d["filter_kolom"])
        data_line = f'"{gc} FROM public.{tn} USING UNIQUE {uid} USING SRID=28992 WHERE {fk} = \'{d["filter_waarde"]}\'"'
    else:
        data_line = f'"{gc} FROM public.{tn} USING UNIQUE {uid} USING SRID=28992"'

    # Fix 2: volledig LABEL blok met OUTLINEWIDTH, FONT, ANTIALIAS, ALIGN en OFFSET
    label_block = ""
    if lbl:
        # OFFSET: voor POINT omhoog zodat label boven het punt staat
        # Voor POLYGON/LINE naast het object
        offset = "-4 -14" if is_point else "-4 -5"
        label_block = (
            "\n      LABEL"
            "\n        COLOR         0 0 0"
            "\n        OUTLINECOLOR  255 255 255"
            "\n        OUTLINEWIDTH  3"
            '\n        FONT          "Ubuntu-MI"'
            "\n        TYPE          truetype"
            "\n        SIZE          11"
            "\n        POSITION      AUTO"
            "\n        PARTIALS      FALSE"
            f"\n        OFFSET        {offset}"
            "\n        ANTIALIAS     true"
            "\n        ALIGN         center"
            f"\n        TEXT          ([{lbl}])"
            "\n      END"
        )

    opacity_line = "\n        OPACITY             20" if is_polygon else ""

    # STYLE blokken afhankelijk van geometrietype
    if is_point:
        # POINT: alleen SYMBOL stip blok — geen ANTIALIAS/OUTLINECOLOR blok
        style_blokken = (
            f'\n      STYLE\n'
            f'        SYMBOL              "stip"\n'
            f'        SIZE                10\n'
            f'        ANTIALIAS           true\n'
            f'        COLOR               "{color}"\n'
            f'      END'
        )
    else:
        # POLYGON / LINE: kleurvlak + outline
        style_blokken = (
            f'\n      STYLE\n'
            f'        ANTIALIAS           true\n'
            f'        COLOR               "{color}"{opacity_line}\n'
            f'      END\n'
            f'      STYLE\n'
            f'        OUTLINECOLOR        "{color}"\n'
            f'        WIDTH               2\n'
            f'      END'
        )

    return (
        f'  LAYER\n'
        f'    NAME                    "{layer_name}"\n'
        f'    GROUP                   "{group_name}"\n'
        f'    INCLUDE                 "connection/dataservices.inc"\n'
        f'    DATA                    {data_line}\n'
        f'    TYPE                    {gt}\n'
        f'    TEMPLATE                "empty"\n'
        f'    PROJECTION\n'
        f'      "init=epsg:28992"\n'
        f'    END\n'
        f'    METADATA\n'
        f'      "ows_title"           "{to_title_case(layer_name)}"\n'
        f'      "ows_abstract"        "{description}"\n'
        f'      "wms_group_title"     "{group_title}"\n'
        f'      "wms_name"            "{layer_name}"\n'
        f'      "wms_format"          "image/png"\n'
        f'      "wms_extent"          "106000 477000 135000 497000"\n'
        f'      "wms_srs"             "{crs}"\n'
        f'      "wms_enable_request"  "*"\n'
        f'      "gml_featureid"       "{uid}"\n'
        f'      "gml_geometries"      "geometry"\n'
        f'      "gml_geometry_type"   "{gml_geo}"\n'
        f'      "gml_include_items"   "all"\n'
        f'      "gml_types"           "auto"\n'
        f'      "wms_include_items"   "all"\n'
        f'    END\n'
        f'    CLASS\n'
        f'      NAME                  "{layer_name}"\n'
        f'      TITLE                 "{to_title_case(layer_name)}"\n'
        + style_blokken
        + f'{label_block}\n'
        f'    END\n'
        f'  END'
    )


# ──────────────────────────────────────────────
# API: Extra laag toevoegen aan bestaande MapFile
# ──────────────────────────────────────────────

@app.route("/api/add-layer", methods=["POST"])
def add_layer():
    """Voegt een LAYER-blok toe aan een bestaande MapFile tekst."""
    data         = request.json
    existing_map = data.get("existing_mapfile", "")
    layer_block  = build_layer_block(data)

    # Verwijder het laatste "END" (MAP-afsluitend) en voeg laag + END terug toe
    lines = existing_map.rstrip().splitlines()
    if lines and lines[-1].strip() == "END":
        lines = lines[:-1]
    new_mapfile = "\n".join(lines) + "\n\n" + layer_block + "\n\nEND"
    return jsonify({"mapfile": new_mapfile})


@app.route("/api/replace-layer", methods=["POST"])
def replace_layer():
    """Vervangt één LAYER-blok (op naam) in een bestaande MapFile."""
    data          = request.json
    existing_map  = data.get("existing_mapfile", "")
    te_vervangen  = data.get("replace_layer_name", "")
    nieuw_blok    = build_layer_block(data)

    if not te_vervangen:
        return jsonify({"error": "Geen laagnaam opgegeven om te vervangen"}), 400

    # Fix 2: update ook de MAP NAME regel als mapfile_naam aanwezig is
    mapfile_naam = data.get("mapfile_naam", "").strip()
    if mapfile_naam:
        updated_lines = []
        for line in existing_map.splitlines():
            stripped = line.strip()
            if stripped.startswith("NAME") and not line.startswith("    "):
                # Alleen de MAP-niveau NAME (2 spaties inspringing)
                if line.startswith("  NAME"):
                    line = f'  NAME                      "{mapfile_naam}"'
            updated_lines.append(line)
        existing_map = "\n".join(updated_lines)

    # Splits de MapFile op in LAYER-blokken en vervang het juiste
    lines      = existing_map.splitlines()
    result     = []
    in_layer   = False
    layer_naam = None
    buffer     = []
    vervangen  = False

    for line in lines:
        stripped = line.strip()

        if not in_layer and stripped == "LAYER":
            in_layer   = True
            layer_naam = None
            buffer     = [line]
            continue

        if in_layer:
            buffer.append(line)
            # Zoek de NAME regel van deze laag
            if layer_naam is None and stripped.startswith("NAME"):
                parts = stripped.split(None, 1)
                if len(parts) > 1:
                    layer_naam = parts[1].strip().strip('"')

            # Einde van dit LAYER-blok
            if stripped == "END" and layer_naam is not None:
                # Tel inspringen: een LAYER-END staat op 2 spaties
                if line.startswith("  END") and not line.startswith("    END"):
                    if layer_naam == te_vervangen and not vervangen:
                        result.append(nieuw_blok)
                        vervangen = True
                    else:
                        result.extend(buffer)
                    in_layer   = False
                    layer_naam = None
                    buffer     = []
                    continue
        else:
            result.append(line)

    # Voeg eventuele resterende buffer toe (veiligheid)
    if buffer:
        result.extend(buffer)

    return jsonify({"mapfile": "\n".join(result)})


# ──────────────────────────────────────────────
# API: MapFile Genereren
# ──────────────────────────────────────────────

@app.route("/api/generate-mapfile", methods=["POST"])
def generate_mapfile():
    data        = request.json
    publisher   = data.get("publisher", "Team Datamanagement")
    group_name  = data.get("wms_groepsnaam", "mijn_groep")
    mapfile_naam = data.get("mapfile_naam", data.get("wms_laagnaam", "mapfile"))
    auth        = data.get("auth", "openbaar")

    layer_block = build_layer_block(data)

    mapfile = (
        f'MAP\n'
        f'  NAME                      "{mapfile_naam}"\n'
        f'  INCLUDE                   "header.inc"\n'
        f'  WEB\n'
        f'    METADATA\n'
        f'      "team"                "{publisher}"\n'
        f'      "ows_title"           "{to_title_case(group_name)}"\n'
        f'      "ows_abstract"        ""\n'
        f'      "auth"                "{auth}"\n'
        f'    END\n'
        f'  END\n'
        f'\n'
        + layer_block +
        f'\n\nEND'
    )
    return jsonify({"mapfile": mapfile.lstrip()})


if __name__ == "__main__":
    # Fix voor Debug Mode alert: debug=False
    app.run(debug=False, port=5000)