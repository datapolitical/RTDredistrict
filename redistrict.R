#!/usr/bin/env Rscript
# Generate an RTD redistricting plan using the redist package.
# Output: a static map JSON file conforming to STATIC_MAP_SPEC.md
#
# Strategy: aggregate precincts into municipality-level blocks.
# Small/medium cities become single atomic units (boundaries follow city limits).
# Cities too large to fit in one district are split to individual precincts.
# Unincorporated precincts are also kept as individual precinct blocks.
# This guarantees district boundaries follow actual city limits.

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
  make_option("--burst_size",  type = "integer",   default = 20,
              help = "MCMC steps per short burst [default 20]"),
  make_option("--max_bursts",  type = "integer",   default = 500,
              help = "Number of bursts [default 500; total steps = burst_size x max_bursts]"),
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
precincts  <- st_transform(precincts, 26913)
precincts$prec_idx <- seq_len(nrow(precincts))   # 1-based row index

cat(sprintf("  %d precincts loaded\n", nrow(precincts)))

# ── Assign municipality to each precinct (centroid containment) ───────────────
cat("Assigning municipalities...\n")
munis <- st_read("rtd_data/municipalities.geojson", quiet = TRUE) |>
  st_transform(26913) |>
  transmute(muni_id = as.character(PLACEFP))

centroids <- st_sf(geometry = st_centroid(st_geometry(precincts)))
muni_join <- st_join(centroids, munis, join = st_within)
precincts$muni_id <- ifelse(is.na(muni_join$muni_id), "unincorp", muni_join$muni_id)

# ── Build municipality-level blocks ───────────────────────────────────────────
# Whole municipalities become single blocks (boundaries follow city limits).
# Municipalities too large to fit in one district are split to individual precincts.
# Unincorporated precincts are also kept as individual precinct blocks.
cat("Building municipality blocks...\n")

total_pop     <- sum(precincts$total_pop)
ideal_pop     <- total_pop / n
max_block_pop <- ideal_pop

muni_pops <- precincts |>
  st_drop_geometry() |>
  group_by(muni_id) |>
  summarize(pop = sum(total_pop), .groups = "drop")

large_munis <- muni_pops |>
  filter(muni_id != "unincorp", pop > max_block_pop) |>
  pull(muni_id)

precincts <- precincts |>
  mutate(block_id = case_when(
    muni_id == "unincorp"      ~ paste0("prec_", prec_idx),  # unincorporated: own precinct block
    muni_id %in% large_munis   ~ paste0("prec_", prec_idx),  # large city: own precinct block
    TRUE                       ~ muni_id                      # small/medium city: whole municipality
  ))

# ── Split non-contiguous municipality blocks into connected components ─────────
# Some municipalities have disconnected geometry (enclaves etc.). A MultiPolygon
# block assigned as one unit makes its district non-contiguous. Split each
# municipality's precincts into connected components using precinct adjacency.
adj_prec_cc <- redist.adjacency(precincts, queen = FALSE)
muni_block_ids <- unique(precincts$block_id[!startsWith(precincts$block_id, "prec_")])
n_splits <- 0L
for (bid in muni_block_ids) {
  rows <- which(precincts$block_id == bid)
  if (length(rows) <= 1L) next
  visited <- logical(length(rows))
  comp    <- integer(length(rows))
  cid     <- 0L
  for (k in seq_along(rows)) {
    if (visited[k]) next
    cid <- cid + 1L
    queue <- k
    while (length(queue) > 0L) {
      cur <- queue[1L]; queue <- queue[-1L]
      if (visited[cur]) next
      visited[cur] <- TRUE; comp[cur] <- cid
      nbrs <- which(rows %in% (adj_prec_cc[[rows[cur]]] + 1L))
      queue <- c(queue, nbrs[!visited[nbrs]])
    }
  }
  if (cid > 1L) {
    n_splits <- n_splits + cid - 1L
    for (c in seq_len(cid))
      precincts$block_id[rows[comp == c]] <- paste0(bid, "_cc", c)
  }
}
if (n_splits > 0L)
  cat(sprintf("  Split %d municipality block(s) into disconnected components\n", n_splits))

# Dissolve into blocks
blocks <- precincts |>
  group_by(block_id) |>
  summarize(
    total_pop = sum(total_pop),
    geometry  = st_union(geometry),
    .groups   = "drop"
  ) |>
  st_as_sf()

n_muni_blocks <- sum(!large_munis %in% muni_pops$muni_id[muni_pops$muni_id == "unincorp"])
cat(sprintf("  %d blocks: %d whole municipalities, %d large municipalities split to precincts\n",
            nrow(blocks), nrow(blocks) - sum(startsWith(blocks$block_id, "prec_")), length(large_munis)))
if (length(large_munis) > 0)
  cat(sprintf("  Large municipalities split to precincts: %s\n",
              paste(large_munis, collapse = ", ")))

# ── Build adjacency graph for blocks ─────────────────────────────────────────
cat("Building block adjacency graph...\n")
adj_blocks <- redist.adjacency(blocks, queen = FALSE)

isolated <- which(sapply(adj_blocks, length) == 0)
if (length(isolated) > 0) {
  cat(sprintf("  Connecting %d isolated block(s)\n", length(isolated)))
  coords <- st_coordinates(st_centroid(st_geometry(blocks)))
  for (i in isolated) {
    dists    <- sqrt((coords[, 1] - coords[i, 1])^2 + (coords[, 2] - coords[i, 2])^2)
    dists[i] <- Inf
    j        <- which.min(dists)
    adj_blocks[[i]] <- c(adj_blocks[[i]], j - 1L)
    adj_blocks[[j]] <- c(adj_blocks[[j]], i - 1L)
  }
}

# ── Build redist map and constraints ─────────────────────────────────────────
cat("Building redist map...\n")
map <- redist_map(blocks,
                  pop_col = "total_pop",
                  adj     = adj_blocks,
                  ndists  = n,
                  pop_tol = 0.10)

constr <- redist_constr(map) |>
  add_constr_splits(strength = 1.5, admin = "block_id")

# ── Run short-burst optimization (Polsby-Popper on clean block shapes) ────────
cat(sprintf("Running short-burst optimization for %d districts...\n", n))
cat(sprintf("  %d bursts x %d steps = %d total steps\n",
            opt$max_bursts, opt$burst_size, opt$max_bursts * opt$burst_size))

plans <- redist_shortburst(
  map,
  score_fn   = scorer_polsby_popper(map, m = 1),
  burst_size = opt$burst_size,
  max_bursts = opt$max_bursts,
  maximize   = TRUE,
  constraints = constr,
  verbose    = FALSE
)

# ── Extract best plan ─────────────────────────────────────────────────────────
plan_matrix <- get_plans_matrix(plans)
pp_scores   <- scorer_polsby_popper(map, m = 1)(plan_matrix)
best_col    <- which.max(pp_scores)

block_assignments <- as.integer(plan_matrix[, best_col])   # 1-indexed district per block

# Map block assignments back to individual precincts
block_dist        <- setNames(block_assignments, blocks$block_id)
precinct_district <- block_dist[precincts$block_id]        # lookup by block_id
assignments       <- as.integer(precinct_district) - 1L    # 0-indexed

# ── Report stats ──────────────────────────────────────────────────────────────
dist_pop <- as.numeric(tapply(precincts$total_pop, precinct_district, sum))
max_dev  <- max(abs(dist_pop - ideal_pop) / ideal_pop)

# Cut edges at the precinct level (what the browser uses for contiguity)
adj_prec <- redist.adjacency(precincts, queen = FALSE)
isolated_p <- which(sapply(adj_prec, length) == 0)
if (length(isolated_p) > 0) {
  coords_p <- st_coordinates(st_centroid(st_geometry(precincts)))
  for (i in isolated_p) {
    dists <- sqrt((coords_p[,1]-coords_p[i,1])^2+(coords_p[,2]-coords_p[i,2])^2)
    dists[i] <- Inf; j <- which.min(dists)
    adj_prec[[i]] <- c(adj_prec[[i]], j-1L)
    adj_prec[[j]] <- c(adj_prec[[j]], i-1L)
  }
}
edges_i <- edges_j <- integer(0)
for (i in seq_along(adj_prec)) {
  nbrs <- adj_prec[[i]] + 1L; nbrs <- nbrs[nbrs > i]
  if (length(nbrs) > 0) { edges_i <- c(edges_i, rep(i, length(nbrs))); edges_j <- c(edges_j, nbrs) }
}
cut_edges <- sum(assignments[edges_i] != assignments[edges_j])

cat(sprintf("Best plan: PP score = %.3f, max pop dev = %.2f%%, cut edges = %d / %d\n",
            pp_scores[best_col], max_dev * 100, cut_edges, length(edges_i)))

if (length(assignments) != nrow(precincts))
  warning(sprintf("Expected %d assignments, got %d", nrow(precincts), length(assignments)))

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

# ── Update static_maps/index.json ─────────────────────────────────────────────
index_path <- file.path("static_maps", "index.json")
index <- if (file.exists(index_path)) fromJSON(index_path, simplifyDataFrame = FALSE) else list()

entry <- list(file = basename(out_file), label = map_name)
existing <- which(vapply(index, function(e) identical(e$file, entry$file), logical(1)))
if (length(existing) > 0) {
  index[[existing[1]]] <- entry
} else {
  index <- c(index, list(entry))
}
index <- index[order(sapply(index, function(e) e$file))]
write_json(index, index_path, auto_unbox = TRUE, pretty = TRUE)
cat(sprintf("Updated %s (%d entries)\n", index_path, length(index)))
