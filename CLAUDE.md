# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Build the precomputed precinct index (run once, or when source GeoJSON data changes)
python3 build_precomputed.py

# Generate a redistricting plan using R + redist package
Rscript redistrict.R --districts 7
Rscript redistrict.R --districts 7 --seed 42 --name "Compact 7"
Rscript redistrict.R --districts 7 --output static_maps/my_map.json
```

Key CLI flags for `redistrict.R`: `--districts` (required, 2–15), `--seed`, `--name`, `--description`, `--output`.

## Architecture

This is a redistricting tool for RTD (Regional Transportation District) in Colorado. The algorithm is implemented in R using the `redist` package and produces static JSON files consumed by a web frontend.

### Data pipeline

```
Source GeoJSON files (rtd_data/)
        |
        v
build_precomputed.py   →   rtd_data/precomputed.json
                           (1,672 precincts with demographics + adjacency graph)
        |
        v
redistrict.R           →   static_maps/districts_N_SEED.json
                           (precinct-to-district assignments)
```

### Key data files

- `rtd_data/precomputed.json` — the primary index: array of precinct objects (demographics, UTM centroids, municipality IDs) plus a precomputed adjacency list. Built by `build_precomputed.py` from `precincts.geojson` and `municipalities.geojson`.
- `rtd_data/precincts.geojson` — source precinct polygons with ACS 2022 5-year demographic fields (`total_pop`, `nh_white`, `nh_black`, `hispanic`, `nh_asian`, etc.)
- `static_maps/` — output directory for generated plans; consumed by a web frontend.

### Algorithm (redistrict.R)

Uses the `redist` package (R). Produces output conforming to `STATIC_MAP_SPEC.md`:
- `assignments[]` — 1,672 integers (0-indexed district IDs)
- `nDistricts`, `name`, `description` fields

### Static map format

Output JSON files have exactly 1,672 integers in `assignments[]` (0-indexed district IDs). See `STATIC_MAP_SPEC.md` for the full spec, including how to add maps to the frontend dropdown via `static_maps/index.json`.

### CRS conventions

- UTM Zone 13N (`EPSG:26913`) — used for all distance/area calculations.
- WGS84 (`EPSG:4326`) — stored in precomputed.json as `lon`/`lat` for display.
- Adjacency uses a 50 m buffer to handle county-boundary slivers; isolated components are connected via nearest-centroid bridge links.
