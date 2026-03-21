#!/usr/bin/env Rscript
# Generate a sample set of redistricting maps and update static_maps/index.json.
# Usage: Rscript generate_samples.R

library(jsonlite)

# ── Define the sample configurations ─────────────────────────────────────────
# Each entry becomes one map. Adjust freely.
configs <- list(
  list(districts = 7, seed = 101, name = "7 Districts (A)", description = "7-district plan, seed 101"),
  list(districts = 7, seed = 202, name = "7 Districts (B)", description = "7-district plan, seed 202"),
  list(districts = 7, seed = 303, name = "7 Districts (C)", description = "7-district plan, seed 303"),
  list(districts = 9, seed = 101, name = "9 Districts (A)", description = "9-district plan, seed 101"),
  list(districts = 9, seed = 202, name = "9 Districts (B)", description = "9-district plan, seed 202"),
  list(districts = 5, seed = 101, name = "5 Districts (A)", description = "5-district plan, seed 101"),
  list(districts = 5, seed = 202, name = "5 Districts (B)", description = "5-district plan, seed 202")
)

# ── Run each configuration ────────────────────────────────────────────────────
dir.create("static_maps", showWarnings = FALSE, recursive = TRUE)
index_entries <- list()

for (cfg in configs) {
  out_file <- sprintf("static_maps/districts_%d_%d.json", cfg$districts, cfg$seed)
  label    <- cfg$name

  cat(sprintf("\n[%s] %d districts, seed %d -> %s\n",
              format(Sys.time(), "%H:%M:%S"), cfg$districts, cfg$seed, out_file))

  args <- c(
    "redistrict.R",
    "--districts", cfg$districts,
    "--seed",      cfg$seed,
    "--name",      shQuote(cfg$name),
    "--description", shQuote(cfg$description),
    "--output",    out_file
  )

  status <- system2("Rscript", args)

  if (status != 0) {
    warning(sprintf("redistrict.R exited with status %d for config: %s", status, cfg$name))
    next
  }

  index_entries <- c(index_entries, list(list(file = basename(out_file), label = label)))
}

# ── Write static_maps/index.json ──────────────────────────────────────────────
index_path <- "static_maps/index.json"
write_json(index_entries, index_path, auto_unbox = TRUE, pretty = TRUE)
cat(sprintf("\nWrote %s with %d entries.\n", index_path, length(index_entries)))
