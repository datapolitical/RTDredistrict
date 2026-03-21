# Static Map File Specification

This document describes the format for pre-built district assignment files that the RTD Redistricting Explorer can load as static maps. Produce these files using redist in R.

---

## Overview

A static map file is a JSON file that assigns each RTD precinct to a numbered district. The website loads it, applies colors, and renders it instantly — no algorithm runs.

---

## File Location

Place files in `static_maps/` at the project root:

```
rtd_data/precomputed.json   ← precinct index (loaded automatically)
static_maps/
  compact_7.json
  minority_7.json
  compact_9.json
  ...
```

---

## File Format

```json
{
  "name": "Compact 7-District Map",
  "description": "Maximizes district compactness, equal population ±3%",
  "nDistricts": 7,
  "assignments": [0, 2, 1, 0, 4, 6, 3, ...]
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Short display name shown in the UI |
| `description` | string | no | Longer explanation shown below the name |
| `nDistricts` | integer | yes | Number of districts (2–15) |
| `assignments` | integer array | yes | District index for each precinct (see below) |

### `assignments` array

- Length must equal **1672** 
- Each value is a **0-indexed** district number: `0` through `nDistricts - 1`
- Order matches the `precincts` array in `precomputed.json` (i.e., `assignments[i]` is the district for `precincts[i]`)
- Value `-1` marks an unallocated precinct (will show as grey and trigger a warning)

**Example:** for 7 districts, valid values are `0, 1, 2, 3, 4, 5, 6` (or `-1` for unallocated).



## Quality Criteria

The website validates and displays:

- **Population balance**: deviation from ideal = `|pop[d] - totalPop/nDistricts| / (totalPop/nDistricts)`. Target: all districts within ±5%.
- **Contiguity**: each district must form a single connected region 

- **Minority opportunity**: at least one district with ≥45% combined Hispanic + Black + Asian population is highlighted.

There are no hard constraints on which criteria your tool must optimize — the UI shows all metrics so users can evaluate the tradeoffs.

---

## How the Website Loads Static Maps


A dropdown in the control panel will list available static maps. Selecting one loads the file and sets the district assignments without running the algorithm. The stats table and comparison panel update identically to a live-computed map.

To add your map to the dropdown, drop the JSON file into `static_maps/` and add an entry to `static_maps/index.json`:

```json
[
  { "file": "compact_7.json",  "label": "Compact 7 districts" },
  { "file": "minority_7.json", "label": "7 districts – minority opportunity" },
  { "file": "compact_9.json",  "label": "Compact 9 districts" }
]
```

---


## Notes

- Precinct positions use UTM Zone 13N (meters) for distance. At Colorado latitude, 1 degree ≈ 88 km E-W, 111 km N-S.
- The `muniId` field lets you minimize split municipalities: count edges `(i, j)` where `muniId[i] == muniId[j] != 0` and `assignments[i] != assignments[j]`.
- Population data is ACS 2022 5-year estimates. The RTD service area has approximately 2.71 million residents across 1,672 precincts.

