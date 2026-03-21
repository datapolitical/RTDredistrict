#!/usr/bin/env python3
"""
Build rtd_data/precomputed.json from source GeoJSON files.

Inputs:
  rtd_data/precincts.geojson     - precinct polygons with ACS demographics
  rtd_data/municipalities.geojson - municipality polygons for muniId assignment

Output:
  rtd_data/precomputed.json      - array of precinct objects + adjacency list

CRS: all spatial ops in UTM Zone 13N (EPSG:26913); lon/lat stored in WGS84.
Adjacency: 50 m buffer to handle county-boundary slivers; isolated precincts
           connected via nearest-centroid bridge links.
"""

import json
import sys
from pathlib import Path

try:
    import numpy as np
    from pyproj import Transformer
    from shapely.geometry import shape, mapping
    from shapely.ops import transform as shp_transform
    from shapely.strtree import STRtree
except ImportError as e:
    sys.exit(f"Missing dependency: {e}\nRun: pip install shapely pyproj numpy")

PRECINCTS_PATH  = Path("rtd_data/precincts.geojson")
MUNIS_PATH      = Path("rtd_data/municipalities.geojson")
OUTPUT_PATH     = Path("rtd_data/precomputed.json")
BUFFER_M        = 50.0   # metres for adjacency detection

# ── CRS transformers ──────────────────────────────────────────────────────────
wgs84_to_utm  = Transformer.from_crs("EPSG:4326", "EPSG:26913", always_xy=True)
utm_to_wgs84  = Transformer.from_crs("EPSG:26913", "EPSG:4326", always_xy=True)

def to_utm(geom):
    return shp_transform(wgs84_to_utm.transform, geom)

# ── Load precincts ────────────────────────────────────────────────────────────
print("Loading precincts …")
with open(PRECINCTS_PATH) as f:
    prec_fc = json.load(f)

features = prec_fc["features"]
n = len(features)
print(f"  {n} precincts found")

# Build UTM geometries and centroid arrays
utm_geoms   = []
centroids_x = []
centroids_y = []
lons        = []
lats        = []

for feat in features:
    g = to_utm(shape(feat["geometry"]))
    utm_geoms.append(g)
    cx, cy = g.centroid.x, g.centroid.y
    centroids_x.append(cx)
    centroids_y.append(cy)
    lon, lat = utm_to_wgs84.transform(cx, cy)
    lons.append(round(lon, 6))
    lats.append(round(lat, 6))

# ── Load municipalities and assign muniId ────────────────────────────────────
print("Loading municipalities …")
with open(MUNIS_PATH) as f:
    muni_fc = json.load(f)

muni_geoms = []
muni_ids   = {}   # PLACEFP -> integer id (1-based; 0 = unincorporated)
muni_id_counter = 1

for feat in muni_fc["features"]:
    placefp = feat["properties"].get("PLACEFP", "")
    if placefp not in muni_ids:
        muni_ids[placefp] = muni_id_counter
        muni_id_counter += 1
    muni_geoms.append((to_utm(shape(feat["geometry"])), muni_ids[placefp]))

# Spatial index for municipalities
muni_tree = STRtree([g for g, _ in muni_geoms])

print("Assigning muniIds …")
muni_id_list = []
for i, g in enumerate(utm_geoms):
    centroid = g.centroid
    hits = muni_tree.query(centroid)
    assigned = 0
    for j in hits:
        mg, mid = muni_geoms[j]
        if mg.contains(centroid):
            assigned = mid
            break
    muni_id_list.append(assigned)

# ── Build adjacency via buffered intersection ────────────────────────────────
print("Building adjacency list (50 m buffer) …")
buffered = [g.buffer(BUFFER_M) for g in utm_geoms]
tree = STRtree(buffered)

adj = [set() for _ in range(n)]
for i, buf in enumerate(buffered):
    candidates = tree.query(buf)
    for j in candidates:
        if j <= i:
            continue
        if buf.intersects(buffered[j]):
            adj[i].add(j)
            adj[j].add(i)
    if (i + 1) % 200 == 0:
        print(f"  {i+1}/{n} …")

# ── Connect isolated components via nearest-centroid bridges ─────────────────
print("Checking connectivity …")
cx = np.array(centroids_x)
cy = np.array(centroids_y)

def find_components(adj_sets, n):
    visited = [-1] * n
    comp = 0
    for start in range(n):
        if visited[start] != -1:
            continue
        stack = [start]
        while stack:
            node = stack.pop()
            if visited[node] != -1:
                continue
            visited[node] = comp
            stack.extend(adj_sets[node] - {node})
        comp += 1
    return visited, comp

visited, num_comp = find_components(adj, n)
print(f"  {num_comp} component(s) before bridging")

if num_comp > 1:
    # For each non-main component, connect to nearest precinct in another component
    from collections import defaultdict
    comp_members = defaultdict(list)
    for i, c in enumerate(visited):
        comp_members[c].append(i)

    main_comp = max(comp_members, key=lambda c: len(comp_members[c]))

    for comp_id, members in comp_members.items():
        if comp_id == main_comp:
            continue
        best_i, best_j, best_d = -1, -1, float("inf")
        for i in members:
            # Distance to all nodes in different components
            mask = np.array([visited[k] != comp_id for k in range(n)])
            dx = cx[mask] - cx[i]
            dy = cy[mask] - cy[i]
            dists = np.sqrt(dx*dx + dy*dy)
            j_local = np.argmin(dists)
            j_global = np.where(mask)[0][j_local]
            d = dists[j_local]
            if d < best_d:
                best_d = d
                best_i, best_j = i, j_global
        adj[best_i].add(best_j)
        adj[best_j].add(best_i)
        print(f"  Bridge: precinct {best_i} <-> {best_j} ({best_d:.0f} m)")

    visited, num_comp = find_components(adj, n)
    print(f"  {num_comp} component(s) after bridging")

# ── Assemble output ───────────────────────────────────────────────────────────
print("Assembling output …")
precincts_out = []
for i, feat in enumerate(features):
    p = feat["properties"]
    precincts_out.append({
        "idx":         i,
        "geoid":       str(p.get("GEOID", "")),
        "countyfp":    str(p.get("COUNTYFP", "")),
        "x":           round(centroids_x[i], 1),
        "y":           round(centroids_y[i], 1),
        "lon":         lons[i],
        "lat":         lats[i],
        "pop":         int(p.get("total_pop", 0)),
        "nh_white":    int(p.get("nh_white", 0)),
        "nh_black":    int(p.get("nh_black", 0)),
        "hispanic":    int(p.get("hispanic", 0)),
        "nh_asian":    int(p.get("nh_asian", 0)),
        "pct_white":   round(float(p.get("pct_white",    0)), 4),
        "pct_black":   round(float(p.get("pct_black",    0)), 4),
        "pct_hispanic":round(float(p.get("pct_hispanic", 0)), 4),
        "pct_asian":   round(float(p.get("pct_asian",    0)), 4),
        "muniId":      muni_id_list[i],
        "hasGeom":     True,
    })

adjacency_out = [sorted(s) for s in adj]

output = {
    "precincts": precincts_out,
    "adjacency": adjacency_out,
}

with open(OUTPUT_PATH, "w") as f:
    json.dump(output, f, separators=(",", ":"))

print(f"\nWrote {OUTPUT_PATH}  ({OUTPUT_PATH.stat().st_size // 1024} KB)")
print("Done.")
