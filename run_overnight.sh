#!/usr/bin/env bash
# run_overnight.sh — generate high-quality redistricting plans overnight
#
# Usage:
#   ./run_overnight.sh                  # 7 districts, run ~300 plans
#   ./run_overnight.sh --districts 5
#   ./run_overnight.sh --districts 7 --plans 100
#
# Strategy: 8 parallel R jobs, each with 5000 bursts (10x the default).
# Plans are named "Overnight #001", "Overnight #002", etc.
# Leave it running overnight; Ctrl+C stops cleanly after the current batch.

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
DISTRICTS=7
TOTAL_PLANS=300
PARALLEL=8          # matches your 10-core Mac (leaves 2 for the OS)
BURSTS=5000         # 100k MCMC steps per plan (vs 10k default)
POP_TOL=0.05        # 5% max population deviation (vs 10% default)
COMPACTNESS=0.5     # gentle compactness nudge
SERIES="Overnight"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --districts)  DISTRICTS="$2";   shift 2 ;;
    --plans)      TOTAL_PLANS="$2"; shift 2 ;;
    --parallel)   PARALLEL="$2";    shift 2 ;;
    --series)     SERIES="$2";      shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

LOG="static_maps/overnight_$(date +%Y%m%d_%H%M%S).log"
mkdir -p static_maps

echo "Starting overnight run: $TOTAL_PLANS plans, $DISTRICTS districts, $PARALLEL parallel"
echo "Settings: $BURSTS bursts, pop_tol=$POP_TOL, compactness=$COMPACTNESS, strict_contiguity"
echo "Log: $LOG"
echo ""

run_one() {
  local n="$1"
  local name
  name=$(printf "%s #%03d" "$SERIES" "$n")
  local ts
  ts=$(date +%Y%m%d_%H%M%S)
  local out="static_maps/${ts}_d$(printf '%02d' "$DISTRICTS")_overnight$(printf '%03d' "$n").json"

  Rscript redistrict.R \
    --districts   "$DISTRICTS" \
    --max_bursts  "$BURSTS" \
    --pop_tol     "$POP_TOL" \
    --compactness_strength "$COMPACTNESS" \
    --strict_contiguity \
    --name        "$name" \
    --output      "$out" \
    2>&1
}

export -f run_one
export DISTRICTS BURSTS POP_TOL COMPACTNESS SERIES

completed=0
batch_start=1

while [[ $completed -lt $TOTAL_PLANS ]]; do
  batch_end=$(( batch_start + PARALLEL - 1 ))
  if [[ $batch_end -gt $TOTAL_PLANS ]]; then
    batch_end=$TOTAL_PLANS
  fi

  echo "[$(date +%H:%M:%S)] Batch: plans $batch_start–$batch_end of $TOTAL_PLANS"

  pids=()
  for n in $(seq "$batch_start" "$batch_end"); do
    run_one "$n" 2>&1 | tee -a "$LOG" | grep "Best plan:" | sed "s/^/  [#$(printf '%03d' $n)] /" &
    pids+=($!)
  done
  wait "${pids[@]}"

  completed=$batch_end
  batch_start=$(( batch_end + 1 ))

  echo "[$(date +%H:%M:%S)] Completed $completed / $TOTAL_PLANS plans"
done

echo ""
echo "Done. $completed plans written to static_maps/"
echo "Full log: $LOG"
