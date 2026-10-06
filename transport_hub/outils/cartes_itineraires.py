import streamlit as st
import sys
import os
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from core import ui

KM_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools", "km_calcul"))
if KM_DIR not in sys.path:
    sys.path.insert(0, KM_DIR)

ui.page("cartes_itineraires")

# ─── État global ─────────────────────────────────────────────────────────────
if "ci_routes" not in st.session_state:
    st.session_state["ci_routes"] = []
if "ci_sel" not in st.session_state:
    st.session_state["ci_sel"] = 0

# ─── Phase 1 : Upload + calcul ───────────────────────────────────────────────
if not st.session_state["ci_routes"]:

    uploaded = st.file_uploader("Fichier Excel source", type=["xlsx"])
    c1, c2 = st.columns(2)
    calculer_peage = c1.checkbox("Calculer les péages", value=False)
    max_workers    = c2.slider("Calculs en parallèle", 1, 4, 2)

    if uploaded and st.button("Calculer les itinéraires", type="primary"):
        import tempfile

        try:
            # Même approche que run_km.py : on charge le package proprement
            import importlib.util

            def _load_module(name, path):
                spec = importlib.util.spec_from_file_location(name, path)
                mod  = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
                return mod

            _mdir = os.path.join(KM_DIR, "modules")

            # Ordre d'import important : dépendances d'abord
            _load_module("modules",                   os.path.join(_mdir, "__init__.py"))
            _load_module("modules.route_optimizer",   os.path.join(_mdir, "route_optimizer.py"))
            _load_module("modules.villes_jalons",     os.path.join(_mdir, "villes_jalons.py"))
            _ro  = _load_module("modules.ptv_router_km",       os.path.join(_mdir, "ptv_router_km.py"))
            _eh  = _load_module("modules.excel_handler_km",    os.path.join(_mdir, "excel_handler_km.py"))
            _rp  = _load_module("modules.routes_preferentielles", os.path.join(_mdir, "routes_preferentielles.py"))

            # Debug : afficher les attributs disponibles si l'import échoue
            if not hasattr(_ro, "calculate_km_route"):
                st.error(f"Attributs de ptv_router_km : {[a for a in dir(_ro) if not a.startswith('_')]}")
                st.stop()

            calculate_km_route = _ro.calculate_km_route
            geocode_address    = _ro.geocode_address
            read_all_sheets    = _eh.read_all_sheets
            get_waypoints      = _rp.get_waypoints

        except Exception as e:
            st.error(f"Import impossible : {e}")
            st.stop()

        raw = uploaded.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(raw)
            tmp_path = tmp.name

        wb, sheets_data = read_all_sheets(tmp_path)
        os.unlink(tmp_path)

        total = sum(len(r) for _, (_, r) in sheets_data.items())
        if total == 0:
            st.warning("Aucun trajet détecté.")
            st.stop()

        routes_ok = []
        lock = threading.Lock()
        prog = st.progress(0, text="Calcul en cours...")
        done = [0]

        echecs = []  # (trajet, motif) — affichés si rien n'est calculé

        def calc(route, sheet):
            o = geocode_address(route["origin"])
            d = geocode_address(route["dest"])
            if not o or not d:
                manquant = " et ".join(x for x, ok in [(route["origin"], o), (route["dest"], d)] if not ok)
                echecs.append((f"{route['origin']} → {route['dest']}", f"adresse non géocodée : {manquant}"))
                return None
            try:
                wp = get_waypoints(route["origin"], route["dest"])
            except Exception:
                wp = []
            data = calculate_km_route(o[0], o[1], d[0], d[1],
                                      waypoints=wp, calculer_peage=calculer_peage)
            if not data or not data.get("polyline_coords"):
                echecs.append((f"{route['origin']} → {route['dest']}", "PTV n'a renvoyé aucun tracé"))
                return None
            return {
                "label":  f"{route['origin']} → {route['dest']}",
                "origin": route["origin"],
                "dest":   route["dest"],
                "km":     data.get("km", 0),
                "peage":  data.get("prix_peage", 0.0),
                "coords": data["polyline_coords"],
            }

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(calc, r, s): r
                       for s, (_, rs) in sheets_data.items() for r in rs}
            for f in as_completed(futures):
                done[0] += 1
                ro = futures[f]
                prog.progress(done[0] / total,
                              text=f"{done[0]}/{total} — {ro['origin']} → {ro['dest']}")
                try:
                    res = f.result()
                    if res:
                        with lock:
                            routes_ok.append(res)
                except Exception as e:
                    echecs.append((f"{ro['origin']} → {ro['dest']}", f"erreur : {e}"))

        prog.empty()

        if not routes_ok:
            st.error("Aucun itinéraire calculé.")
            cle = str(getattr(_ro, "PTV_API_KEY", "") or "")
            if not cle or cle == "METS_TA_CLE_ICI":
                st.warning("La clé PTV_API_KEY n'est pas lue par l'application : sans elle, aucune adresse "
                           "ne peut être géocodée. Ajoutez-la dans les secrets (au premier niveau), "
                           "puis redémarrez l'app (Reboot).")
            if echecs:
                import pandas as pd
                with st.expander(f"Détail des échecs ({len(echecs)})", expanded=True):
                    st.dataframe(pd.DataFrame(echecs, columns=["Trajet", "Motif"]),
                                 hide_index=True, use_container_width=True)
        else:
            routes_ok.sort(key=lambda r: r["label"])
            st.session_state["ci_routes"] = routes_ok
            st.session_state["ci_sel"] = 0
            st.rerun()

# ─── Phase 2 : Affichage carte ───────────────────────────────────────────────
else:
    routes = st.session_state["ci_routes"]

    # Bouton reset
    if st.button("Nouveau calcul"):
        st.session_state["ci_routes"] = []
        st.session_state["ci_sel"] = 0
        st.rerun()

    # Sélecteur
    labels = [
        f"{r['origin']} → {r['dest']}  |  {r['km']:.0f} km"
        + (f"  ·  {r['peage']:.2f} €" if r['peage'] else "")
        for r in routes
    ]
    sel = st.selectbox(
        f"{len(routes)} itinéraire{'s' if len(routes) > 1 else ''}",
        range(len(routes)),
        format_func=lambda i: labels[i],
        index=st.session_state["ci_sel"],
    )
    # Mettre à jour l'index sans rerun — la carte se met à jour via JS
    st.session_state["ci_sel"] = sel

    r = routes[sel]
    st.caption(
        f"**{r['origin']}** → **{r['dest']}**  ·  📏 {r['km']:.1f} km"
        + (f"  ·  🛣️ {r['peage']:.2f} €" if r['peage'] else "")
    )

    # Carte
    all_coords = [c for ro in routes for c in ro["coords"]]
    center_lat = sum(c[0] for c in all_coords) / len(all_coords)
    center_lon = sum(c[1] for c in all_coords) / len(all_coords)
    routes_js  = json.dumps([
        {"origin": ro["origin"], "dest": ro["dest"],
         "km": ro["km"], "peage": ro["peage"], "coords": ro["coords"]}
        for ro in routes
    ])

    carte_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <script src="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js"></script>
  <link href="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css" rel="stylesheet"/>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text','Inter','Helvetica Neue',Arial,sans-serif; }}
    #map {{ height:700px; width:100%; border-radius:18px;
            box-shadow:0 1px 2px rgba(0,0,0,.04), 0 0 0 .5px rgba(0,0,0,.08); }}
    .panel {{
      background:rgba(255,255,255,0.88); backdrop-filter:saturate(180%) blur(20px);
      padding:12px 16px; border-radius:14px;
      font-size:13px; line-height:1.7; color:#1d1d1f;
      box-shadow:0 4px 24px rgba(0,0,0,0.12);
      min-width:180px; max-width:280px;
      position:absolute; bottom:24px; right:12px; z-index:10;
    }}
    .panel b {{ color:#1d1d1f; font-weight:600; }}
    .panel .km {{ color:#0071e3; font-weight:600; }}
    .mk {{
      width:28px; height:28px; border-radius:50% 50% 50% 0;
      transform:rotate(-45deg); display:flex; align-items:center;
      justify-content:center; font-weight:800; font-size:12px;
      color:white; border:2px solid white;
      box-shadow:0 2px 6px rgba(0,0,0,0.4);
    }}
    .mk span {{ transform:rotate(45deg); }}
    .A {{ background:#34c759; }} .B {{ background:#ff3b30; }}
  </style>
</head>
<body>
<div id="map"></div>
<div class="panel" id="info-panel">
  <b>Chargement...</b>
</div>
<script>
  var ROUTES = {routes_js};
  var currentLine = null, markerA = null, markerB = null;

  var map = new maplibregl.Map({{
    container: 'map',
    style: 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json',
    center: [{center_lon}, {center_lat}],
    zoom: 5
  }});

  map.addControl(new maplibregl.NavigationControl(), 'top-right');

  function mkMarkerEl(cls) {{
    var el = document.createElement('div');
    el.className = 'mk ' + cls;
    var sp = document.createElement('span');
    sp.textContent = cls;
    el.appendChild(sp);
    return el;
  }}

  function show(idx) {{
    var r = ROUTES[idx];
    if (!r || !r.coords || !r.coords.length) return;

    // Convertir [[lat,lon],...] → [[lon,lat],...] pour MapLibre
    var coords = r.coords.map(function(c) {{ return [c[1], c[0]]; }});

    // Supprimer ancienne couche
    if (currentLine) {{
      if (map.getLayer('route-line')) map.removeLayer('route-line');
      if (map.getSource('route-source')) map.removeSource('route-source');
      currentLine = null;
    }}
    if (markerA) {{ markerA.remove(); markerA = null; }}
    if (markerB) {{ markerB.remove(); markerB = null; }}

    // Ajouter la nouvelle polyline
    map.addSource('route-source', {{
      type: 'geojson',
      data: {{
        type: 'Feature',
        geometry: {{ type: 'LineString', coordinates: coords }}
      }}
    }});
    map.addLayer({{
      id: 'route-line',
      type: 'line',
      source: 'route-source',
      layout: {{ 'line-join': 'round', 'line-cap': 'round' }},
      paint: {{ 'line-color': '#0071e3', 'line-width': 5, 'line-opacity': 0.9 }}
    }});
    currentLine = true;

    // Zoom sur le tracé
    var bounds = coords.reduce(function(b, c) {{
      return b.extend(c);
    }}, new maplibregl.LngLatBounds(coords[0], coords[0]));
    map.fitBounds(bounds, {{ padding: 60 }});

    // Marqueurs
    markerA = new maplibregl.Marker({{ element: mkMarkerEl('A'), anchor: 'bottom' }})
      .setLngLat(coords[0])
      .setPopup(new maplibregl.Popup().setHTML('<b>🟢 ' + r.origin + '</b>'))
      .addTo(map);
    markerB = new maplibregl.Marker({{ element: mkMarkerEl('B'), anchor: 'bottom' }})
      .setLngLat(coords[coords.length-1])
      .setPopup(new maplibregl.Popup().setHTML('<b>🔴 ' + r.dest + '</b>'))
      .addTo(map);

    // Panneau info
    var km_s  = r.km    ? '📏 <span class="km">' + r.km.toFixed(1) + ' km</span>' : '';
    var pe_s  = r.peage ? '<br>🛣️ ' + r.peage.toFixed(2) + ' €' : '';
    document.getElementById('info-panel').innerHTML =
      '<b>' + r.origin + '</b><br>→ <b>' + r.dest + '</b><br>' + km_s + pe_s;
  }}

  map.on('load', function() {{
    show({sel});
  }});

  window.addEventListener('message', function(e) {{
    if (e.data && typeof e.data.idx === 'number') show(e.data.idx);
  }});
</script>
</body>
</html>"""

    st.components.v1.html(carte_html, height=720, scrolling=False)

    # ─── Tableau récapitulatif sous la carte ─────────────────────────────────
    st.divider()
    st.markdown("#### 📋 Récapitulatif des trajets")

    import pandas as pd

    total_km    = sum(r["km"]    for r in routes if r["km"])
    total_peage = sum(r["peage"] for r in routes if r["peage"])

    col_t1, col_t2, col_t3 = st.columns(3)
    col_t1.metric("Trajets", len(routes))
    col_t2.metric("Total KM", f"{total_km:,.0f} km")
    if total_peage:
        col_t3.metric("Total Péage", f"{total_peage:,.2f} €")

    df = pd.DataFrame([
        {
            "N°":          i + 1,
            "Chargement":  r["origin"],
            "Déchargement": r["dest"],
            "KM":          f"{r['km']:.1f}" if r["km"] else "—",
            "Péage (€)":   f"{r['peage']:.2f}" if r["peage"] else "—",
        }
        for i, r in enumerate(routes)
    ])

    # Surligner la ligne sélectionnée
    def highlight_sel(row):
        return ["background-color: #e8f1fc; font-weight: bold"
                if row["N°"] == sel + 1
                else "" for _ in row]

    st.dataframe(
        df.style.apply(highlight_sel, axis=1),
        use_container_width=True,
        hide_index=True,
        height=min(400, 38 * len(routes) + 40),
    )
