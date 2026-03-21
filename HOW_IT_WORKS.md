# How the RTD Redistricting Explorer Works

This document explains the full pipeline from raw geographic data to a rendered district map in the browser.

---

## Overview

```
Raw GeoJSON files
      │
      ▼
build_precomputed.py   →   rtd_data/precomputed.json   (precinct index + adjacency graph)
      │
      ▼
redistrict.R           →   static_maps/*.json           (precinct-to-district assignments)
      │
      ▼
index.html             →   browser renders dissolved district fills
```

---

## Step 1 — Building the Precinct Index (`build_precomputed.py`)

The script reads three GeoJSON source files and produces a single compact JSON index used by both the algorithm and the browser.

### What it does

**Clips precincts to the RTD boundary.**
Each of the 1,672 precinct polygons is intersected with `rtd_boundary.geojson`. About 91 precincts extend partially outside the service area and are clipped; a handful that fall entirely outside are kept as-is so no precinct is lost. All geometry is reprojected to UTM Zone 13N (EPSG:26913) for accurate distance and area calculations.

**Assigns municipality IDs.**
Each precinct centroid is tested for containment in `municipalities.geojson`. The result is a `muniId` integer on each precinct record, used later as a grouping key.

**Builds the adjacency graph.**
Every precinct is buffered by 50 metres and tested for intersection with its neighbours. The buffer handles county-boundary slivers where two precincts share a legal border but their digitised edges don't quite touch. This produces a graph of ~5,365 edges across 1,672 nodes.

After geographic adjacency is computed it is saved as `geoAdjacency`. Then isolated components (precincts that share no border with any other) are connected to their nearest centroid via bridge edges, producing `adjacency`. In practice there is one bridge: precinct 191 ↔ 192, ~1,683 m apart.

**Computes current district stats.**
Precinct centroids are tested for containment in each of the 15 director district polygons from `DirectorDistricts.geojson`. Population and demographic totals are aggregated per district and stored as `currentDistrictStats`.

### Output fields in `precomputed.json`

| Field | Contents |
|-------|----------|
| `precincts` | 1,672 records — centroid (lon/lat + UTM x/y), population, race/ethnicity counts, `muniId` |
| `adjacency` | Neighbour lists including bridge edges — used by the browser for contiguity checks |
| `geoAdjacency` | Neighbour lists for real shared-border edges only |
| `muniGroups` | Lists of precinct indices grouped by municipality |
| `countyGroups` | Lists of precinct indices grouped by county |
| `currentDistrictStats` | Pop + demographic totals for the existing 15 director districts |

---

## Step 2 — Generating a District Plan (`redistrict.R`)

The R script uses the [`redist`](https://alarm-redist.org/redist/) package to sample valid redistricting plans via Markov chain Monte Carlo, then selects the best one.

### Algorithm: merge-split MCMC

`redist_mergesplit` runs 2,000 iterations (after 1,000 warm-up steps). Each iteration:

1. Randomly picks two adjacent districts.
2. Merges them into one region.
3. Draws a new split of that region using a random spanning tree, producing two new districts.
4. Accepts or rejects the split based on a Metropolis–Hastings criterion that enforces the population tolerance (±7%).

This explores the space of valid plans while always maintaining contiguity and approximate population balance.

### Selecting the best plan

After sampling, plans are scored on two criteria:

**Population deviation** — `|district_pop − ideal_pop| / ideal_pop`. Plans with max deviation above 5% are deprioritised (fallback threshold: 7%).

**Cut edges** — count of adjacency edges where the two endpoints are in different districts. Fewer cut edges means district boundaries cross fewer precinct borders, producing simpler, straighter lines.

Among plans within the deviation threshold, the one with the fewest cut edges is chosen.

### Output

A JSON file with an `assignments` array of 1,672 integers (0-indexed district IDs), plus `name`, `description`, and `nDistricts`. See `STATIC_MAP_SPEC.md` for the full format.

---

## Step 3 — Rendering in the Browser (`index.html`)

The browser loads `precomputed.json` and the selected static map file, then renders two side-by-side Leaflet maps.

### Loading precinct geometry

On startup the browser fetches `rtd_data/precincts.topo.json` (2.4 MB TopoJSON, converted from 16 MB GeoJSON via `topojson-server` at quantization 5000). If that file is absent it falls back to `precincts.geojson` directly. The resulting GeoJSON FeatureCollection is held in memory and reused for every map load.

### Dissolving precincts into districts

When a static map is selected, `applyMap()` runs:

```
assignments[]  +  precinctsGeoJSON
        │
        ▼
tag each of 1,672 features with its district ID (_district property)
        │
        ▼
turf.flatten()      — splits any MultiPolygon precincts into simple Polygons
        │
        ▼
turf.dissolve()     — merges all features sharing the same _district value
                      into a single (possibly multi-part) polygon per district
        │
        ▼
turf.simplify()     — smooths the merged outline (tolerance 0.002°)
                      removes micro-jags from precinct edge digitisation
        │
        ▼
L.geoJSON()         — renders filled, white-bordered district polygons
```

The dissolve is the key step: it fuses all precinct polygons assigned to the same district into one contiguous shape, erasing the internal precinct seams. Without it, each precinct would render as a separate polygon and overlapping strokes would create visible grid lines.

### Why the proposed maps look more jagged than the 15-director map

The 15-director map was drawn by hand to follow major roads, city limits, and county lines — all of which are smooth, straight, or gently curved. The algorithm knows nothing about roads or city boundaries. It works purely on precinct adjacency, so district borders land wherever the population balance happens to split the precinct graph — often cutting across neighbourhoods rather than following the street grid.

The cut-edge scoring reduces this by preferring plans where fewer precinct boundaries are crossed, but it cannot make a boundary smooth if the underlying precincts along that boundary are small and irregular.

### Layer stack (proposed map, bottom to top)

| Layer | Purpose |
|-------|---------|
| CartoDB light tile layer | Base map — streets and labels |
| `districtLayer` | Dissolved district fills with white borders |
| Inverse RTD mask | Off-white overlay covering everything outside the service area |
| Municipality boundaries | Faint dark-blue lines for geographic context |
| Precinct boundary overlay | Optional white outlines of actual precinct shapes (toggle) |
| Invisible hover layer | Transparent precinct polygons that capture mouse events for tooltips |
| RTD boundary outline | Black border of the service area, always on top |

### Right panel — current 15-director map

`DirectorDistricts.geojson` is rendered directly as a `L.geoJSON` layer using the original district polygons (not dissolved from precincts). Small disconnected slivers are filtered out before rendering. The same inverse mask and RTD outline are applied for visual consistency.

---

## Key Numbers

| Fact | Value |
|------|-------|
| Precincts | 1,672 |
| Total RTD population (ACS 2022) | ~2.71 million |
| Adjacency edges | ~5,365 |
| Bridge edges added | 1 (precinct 191 ↔ 192) |
| MCMC iterations | 2,000 (+ 1,000 warm-up) |
| Population tolerance | ±7% (target ±5%) |
| TopoJSON file size | 2.4 MB (vs 16 MB source GeoJSON) |
