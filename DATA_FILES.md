# Data Files Reference

This document describes every file the app loads at runtime, what it contains, and how the map uses it.

---

## Files Loaded at Startup

### `rtd_data/precomputed.json`

The primary data file. Built offline by `scripts/precompute.py` from the raw source files below. Contains everything the redistricting algorithm and stats panel need, compact enough to load quickly.

**Fields extracted at runtime:**

| Field | Type | Used for |
|-------|------|----------|
| `precincts` | array of objects | One record per precinct (see below) |
| `adjacency` | array of arrays | Neighbor lists including artificial bridge edges across geographic gaps |
| `geoAdjacency` | array of arrays | Neighbor lists for real shared-border edges only (no bridges) |
| `muniGroups` | array of arrays | Lists of precinct indices that share a municipality |
| `countyGroups` | array of arrays | Lists of precinct indices that share a county |
| `currentDistrictStats` | object | Population and demographic stats for the existing 15 districts |

**Each precinct record:**

| Field | Description |
|-------|-------------|
| `idx` | Integer index (matches position in array) |
| `geoid` | Census GEOID string from source precinct file |
| `lon`, `lat` | Centroid in WGS84 degrees |
| `x`, `y` | Centroid in UTM Zone 13N meters (used for distance calculations) |
| `pop` | Total population (ACS 2022 5-year estimates) |
| `nh_white`, `nh_black`, `hispanic`, `nh_asian` | Raw population counts by race/ethnicity |
| `pct_white`, `pct_hispanic`, `pct_black`, `pct_asian` | Percentages |
| `hasGeom` | Whether the source feature had a non-empty geometry |

**How it drives the map:**
The algorithm runs entirely on this data — `pop` for balance, `x`/`y` for compactness, adjacency for contiguity. The map renders district fills by building a **Voronoi tessellation** from `lon`/`lat` centroids: each precinct gets a cell that covers the area closest to its centroid. Cells are merged by district assignment to produce filled regions. This means the colored fills are *approximations* of precinct shapes, not the exact boundaries.

---

### `rtd_data/rtd_boundary.geojson`

The RTD service area boundary polygon.

**Used for:**
- Drawing the blue border around the service area on both maps
- Applying an inverse mask (off-white overlay) that covers everything outside the boundary, hiding Voronoi cells that extend beyond the service area
- Clipping the Voronoi bounding box

---

### `rtd_data/municipalities.geojson`

City and municipality boundary polygons within the RTD area.

**Used for:**
- Drawing faint dark-blue municipal boundary lines on both maps (decorative context layer, not interactive)
- The "city integrity" optimization weight in the algorithm uses `muniGroups` from `precomputed.json`, not this file directly

---

### `DirectorDistricts.geojson`

The current official RTD 15-director district map.

**Used for:**
- Rendering the right-hand "Current: 15-Director RTD Map" panel
- Each feature has a `BND` property (letter A–O) used to assign colors and labels

Small disconnected slivers are filtered out at load time (`dropSmallDistrictParts`) to clean up the display.

---

### `rtd_data/precincts.topo.json`

Actual precinct boundary polygons in TopoJSON format (1.85 MB). Built offline from `precincts.geojson` by running it through `topojson-server` at quantization 5000.

**Used for:**
- The optional "Show precinct boundaries" overlay on both maps
- Rendered with Leaflet's canvas renderer (single `<canvas>` element instead of 1,672 SVG paths)
- Hover tooltip shows precinct index number
- Only loaded if the file exists (graceful fallback if missing)

**Why TopoJSON instead of GeoJSON:**
The source `precincts.geojson` is 16 MB. TopoJSON shares arc coordinates between adjacent polygons and quantizes coordinates, reducing it to 1.85 MB. The TopoJSON client (`vendor/topojson-client.js`) converts it back to GeoJSON at render time.

---

### `static_maps/index.json`

Index of pre-built district assignment files.

**Used for:**
- Populating the "Load static map" dropdown in the controls panel
- Each entry has a `file` (filename in `static_maps/`) and a `label` (display name)
- If the file returns a 404, the dropdown is not shown

Individual static map files (e.g. `static_maps/districts_7_083756.json`) are fetched on demand when selected. See `STATIC_MAP_SPEC.md` for their format.

---

## Source Files (not loaded at runtime)

These files are used only by the offline preprocessing scripts.

| File | Contents |
|------|----------|
| `rtd_data/precincts.geojson` | 1,672 VEST 2024 Colorado election precincts clipped to the RTD boundary, with ACS 2022 demographics interpolated via block-group areal weighting. Source of all precinct geometry and centroid data. |
| `rtd_data/empty_patches.geojson` | 21 geographic gaps (parks, reservoirs, highway interchanges) with nearest-precinct assignments, used to fill visual voids in the Voronoi map |
| `rtd_data/tracts.geojson` | Census block group geometry and demographics used during the interpolation step in precompute |

---

## Why the Voronoi Map and the Precinct Overlay Don't Match Exactly

The colored district fills use **Voronoi cells** (one convex polygon per centroid). The precinct overlay uses **actual precinct polygons** from `precincts.topo.json`. They differ because:

1. **Shape**: Voronoi cells are always convex; many real precincts are not
2. **Multi-part precincts**: 29 precincts are `MultiPolygon` features (split by rivers, highways, etc.). The Voronoi assigns one cell to the centroid, which may not cover both pieces
3. **Holes**: 33 precincts have interior holes (parks, etc.). Voronoi cells have no holes
4. **Edges**: Voronoi boundaries follow equidistant lines between centroids; real precinct boundaries follow streets, rivers, and survey lines

For redistricting purposes these differences don't matter — the algorithm works on precinct units and their adjacency, not their visual shapes. The Voronoi map is a fast, seamless rendering technique. Toggle on the precinct overlay to see the actual boundaries.
