#!/usr/bin/env Rscript
# Render a static map JSON file to a PNG image.
# Usage: Rscript render_map.R --input static_maps/foo.json --output static_maps/foo.png

suppressPackageStartupMessages({
  library(optparse)
  library(sf)
  library(ggplot2)
  library(dplyr)
  library(jsonlite)
})

option_list <- list(
  make_option("--input",  type = "character", help = "Path to static map JSON file"),
  make_option("--output", type = "character", help = "Output PNG path")
)
opt <- parse_args(OptionParser(option_list = option_list))
if (is.null(opt$input))  stop("--input is required")
if (is.null(opt$output)) stop("--output is required")

plan        <- fromJSON(opt$input)
sf_use_s2(FALSE)
precincts   <- st_read("rtd_data/precincts.geojson", quiet = TRUE) |> st_make_valid()
precincts$district <- factor(plan$assignments + 1L)

district_colors <- c(
  "#4E79A7", "#F28E2B", "#E15759", "#76B7B2",
  "#59A14F", "#EDC948", "#B07AA1", "#FF9DA7",
  "#9C755F", "#BAB0AC", "#D37295", "#A0CBE8"
)
n <- plan$nDistricts
palette <- district_colors[seq_len(n)]

p <- ggplot(precincts) +
  geom_sf(aes(fill = district), color = NA, linewidth = 0) +
  geom_sf(aes(group = district), fill = NA, color = "white",
          linewidth = 0.3,
          data = precincts |>
            group_by(district) |>
            summarize(geometry = st_union(geometry), .groups = "drop")) +
  scale_fill_manual(
    values   = palette,
    name     = "District",
    labels   = paste("District", seq_len(n))
  ) +
  labs(title = plan$name) +
  theme_void(base_size = 13) +
  theme(
    plot.title       = element_text(hjust = 0.5, margin = margin(b = 6)),
    legend.position  = "right",
    plot.background  = element_rect(fill = "white", color = NA)
  )

ggsave(opt$output, p, width = 10, height = 7, dpi = 150, bg = "white")
cat(sprintf("Wrote %s\n", opt$output))
