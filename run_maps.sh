#!/bin/bash
# Run from the project root: bash run_maps.sh
# Generates 10 maps with 10,000 MCMC iterations (5x longer than default).
# Each map takes ~5–10 minutes. Total: ~1 hour.
# Increase --nsims further (e.g. 50000) for an even more thorough search.

set -e
cd "$(dirname "$0")"

BURST_SIZE=20   # MCMC steps per burst
MAX_BURSTS=500  # number of bursts (total steps = BURST_SIZE × MAX_BURSTS = 10,000)
                # increase MAX_BURSTS for a more thorough search, e.g. 2000 for ~1hr per map

run() {
  echo "========================================"
  echo "Running: $*"
  echo "========================================"
  Rscript redistrict.R "$@" --burst_size $BURST_SIZE --max_bursts $MAX_BURSTS
}

run --districts 3  --seed 101 --name "3 Districts"  --output static_maps/d03_s101.json
run --districts 5  --seed 202 --name "5 Districts"  --output static_maps/d05_s202.json
run --districts 6  --seed 303 --name "6 Districts"  --output static_maps/d06_s303.json
run --districts 7  --seed 404 --name "7 Districts"  --output static_maps/d07_s404.json
run --districts 8  --seed 505 --name "8 Districts"  --output static_maps/d08_s505.json
run --districts 9  --seed 606 --name "9 Districts"  --output static_maps/d09_s606.json
run --districts 10 --seed 707 --name "10 Districts" --output static_maps/d10_s707.json
run --districts 11 --seed 808 --name "11 Districts" --output static_maps/d11_s808.json
run --districts 13 --seed 909 --name "13 Districts" --output static_maps/d13_s909.json
run --districts 15 --seed 111 --name "15 Districts" --output static_maps/d15_s111.json

echo ""
echo "All done. Updating static_maps/index.json..."

cat > static_maps/index.json << 'EOF'
[
  {"file":"d03_s101.json","label":"3 Districts"},
  {"file":"d05_s202.json","label":"5 Districts"},
  {"file":"d06_s303.json","label":"6 Districts"},
  {"file":"d07_s404.json","label":"7 Districts"},
  {"file":"d08_s505.json","label":"8 Districts"},
  {"file":"d09_s606.json","label":"9 Districts"},
  {"file":"d10_s707.json","label":"10 Districts"},
  {"file":"d11_s808.json","label":"11 Districts"},
  {"file":"d13_s909.json","label":"13 Districts"},
  {"file":"d15_s111.json","label":"15 Districts"}
]
EOF

echo "Done. Reload the browser to see the new maps."
