#!/usr/bin/env Rscript
# Generate an RTD redistricting plan using the redist package.
# Output: a static map JSON file conforming to STATIC_MAP_SPEC.md

suppressPackageStartupMessages({
  library(optparse)
  library(sf)
  library(redist)
  library(dplyr)
  library(jsonlite)
})

# ── CLI arguments ─────────────────────────────────────────────────────────────
option_list <- list(
  make_option("--districts",   type = "integer",   default = NULL,
              help = "Number of districts, 2–15 [required]"),
  make_option("--seed",        type = "integer",   default = NULL,
              help = "Random seed for reproducibility"),
  make_option("--name",        type = "character", default = NULL,
              help = "Short display name shown in the UI"),
  make_option("--description", type = "character", default = "",
              help = "Longer description shown below the name"),
  make_option("--output",      type = "character", default = NULL,
              help = "Output file path (default: static_maps/districts_N_SEED.json)")
)

opt <- parse_args(OptionParser(
  option_list = option_list,
  description = "Generate an RTD redistricting plan and write a static map JSON file."
))

# ── Validate ──────────────────────────────────────────────────────────────────
if (is.null(opt$districts)) stop("--districts is required")
n <- as.integer(opt$districts)
if (n < 2 || n > 15)        stop("--districts must be between 2 and 15")

if (!is.null(opt$seed)) set.seed(opt$seed)

seed_tag <- if (!is.null(opt$seed)) opt$seed else format(Sys.time(), "%H%M%S")
out_file  <- if (!is.null(opt$output)) opt$output else
               file.path("static_maps", paste0("districts_", n, "_", seed_tag, ".json"))
map_name  <- if (!is.null(opt$name)) opt$name else paste(n, "District Map")

# ── Load precincts ────────────────────────────────────────────────────────────
cat("Loading precincts...\n")
if (!file.exists("rtd_data/precincts.geojson"))
  stop("rtd_data/precincts.geojson not found. Run from the project root.")

precincts <- st_read("rtd_data/precincts.geojson", quiet = TRUE)
precincts  <- st_transform(precincts, 26913)   # UTM Zone 13N for accurate geometry

cat(sprintf("  %d precincts loaded\n", nrow(precincts)))

# ── Build adjacency graph with fixes for isolated / disconnected precincts ────
cat("Building adjacency graph...\n")
adj <- redist.adjacency(precincts)

# Connect any precinct with no neighbors to its nearest centroid
isolated <- which(sapply(adj, length) == 0)
if (length(isolated) > 0) {
  cat(sprintf("  Connecting %d isolated precinct(s): %s\n",
              length(isolated), paste(isolated, collapse = ", ")))
  coords <- st_coordinates(st_centroid(st_geometry(precincts)))
  for (i in isolated) {
    dists    <- sqrt((coords[, 1] - coords[i, 1])^2 + (coords[, 2] - coords[i, 2])^2)
    dists[i] <- Inf
    j        <- which.min(dists)
    adj[[i]] <- c(adj[[i]], j - 1L)
    adj[[j]] <- c(adj[[j]], i - 1L)
  }
}

# ── Build redist map ──────────────────────────────────────────────────────────
cat("Building redist map...\n")
map <- redist_map(precincts,
                  pop_col  = "total_pop",
                  adj      = adj,
                  ndists   = n,
                  pop_tol  = 0.05)

# ── Run merge-split MCMC ──────────────────────────────────────────────────────
cat(sprintf("Running merge-split MCMC for %d districts...\n", n))
plans <- redist_mergesplit(map, nsims = 2000, warmup = 1000,
                           compactness = 1, verbose = FALSE)

# ── Select best plan: most compact among those within population tolerance ─────
total_pop <- sum(precincts$total_pop)
ideal     <- total_pop / n

pop_scores <- plans %>%
  mutate(pop_dev = abs(total_pop - ideal) / ideal) %>%
  group_by(draw) %>%
  summarize(max_dev = max(pop_dev), .groups = "drop")

comp_scores <- plans %>%
  mutate(polsby = distr_compactness(map, measure = "PolsbyPopper")) %>%
  as_tibble() %>%
  group_by(draw) %>%
  summarize(mean_polsby = mean(polsby, na.rm = TRUE), .groups = "drop")

best_summary <- pop_scores %>%
  left_join(comp_scores, by = "draw") %>%
  filter(max_dev <= 0.05) %>%
  slice_max(mean_polsby, n = 1, with_ties = FALSE)

# Fall back to best population deviation if nothing meets the tolerance
if (nrow(best_summary) == 0) {
  best_summary <- pop_scores %>%
    left_join(comp_scores, by = "draw") %>%
    slice_min(max_dev, n = 1, with_ties = FALSE)
}

best_draw <- as.character(best_summary$draw)
cat(sprintf("Best plan: max pop dev = %.2f%%, mean Polsby-Popper = %.3f\n",
            best_summary$max_dev * 100, best_summary$mean_polsby))

# Extract assignments and convert to 0-indexed integers
plan_matrix <- get_plans_matrix(plans)
best_col    <- as.integer(best_draw)
assignments <- as.integer(plan_matrix[, best_col]) - 1L

if (length(assignments) != 1672)
  warning(sprintf("Expected 1672 assignments, got %d", length(assignments)))

# ── Write output ──────────────────────────────────────────────────────────────
dir.create("static_maps", showWarnings = FALSE, recursive = TRUE)

result <- list(
  name        = map_name,
  description = opt$description,
  nDistricts  = n,
  assignments = assignments
)

write_json(result, out_file, auto_unbox = TRUE, pretty = FALSE)
cat(sprintf("Wrote %s\n", out_file))
