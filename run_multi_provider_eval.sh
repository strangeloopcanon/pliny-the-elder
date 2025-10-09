#!/bin/bash
# Multi-provider eval script for VEI
# Generates a deterministic dataset, runs vei-llm-test across providers, and scores results.

set -euo pipefail

# Load .env file if present
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# -----------------------------------------------------------------------------
# Configuration (override via environment variables)
# -----------------------------------------------------------------------------
SEED="${VEI_SEED:-42042}"
ROLLOUT_EPISODES="${VEI_ROLLOUT_EPISODES:-2}"
DATASET_PATH="${VEI_DATASET:-_vei_out/rollout_eval.json}"
MAX_STEPS="${VEI_MAX_STEPS:-40}"
TASK="${VEI_TASK:-Research MacroBook Pro 16 specs from vweb.local/pdp/macrobook-pro-16, secure Slack approval under \$3200, and email sales@macrocompute.example for price & ETA.}"

ARTIFACT_ROOT="${VEI_ARTIFACTS_DIR:-_vei_out/llm_eval}"
RUN_STAMP=$(date +%Y%m%d_%H%M%S)
RUN_DIR="$ARTIFACT_ROOT/multi_provider_${RUN_STAMP}"

# Models to test (model:provider)
declare -a MODELS=(
  "gpt-5:openai"
  "gpt-5-codex:openai"
  "claude-sonnet-4-5:anthropic"
  "x-ai/grok-4:openrouter"
  "models/gemini-2.5-flash:google"
)

# ANSI colors (fallback to plain text when stdout isn't a terminal)
if [ -t 1 ]; then
  GREEN='\033[0;32m'
  RED='\033[0;31m'
  YELLOW='\033[1;33m'
  NC='\033[0m'
else
  GREEN=''
  RED=''
  YELLOW=''
  NC=''
fi

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
require_command() {
  local cmd=$1
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "${RED}ERROR:${NC} Required command '$cmd' not found in PATH" >&2
    exit 1
  fi
}

ensure_dataset() {
  if [ -f "$DATASET_PATH" ]; then
    echo "${YELLOW}Dataset already present:${NC} $DATASET_PATH"
    return
  fi

  echo "${YELLOW}Generating dataset with vei-rollout...${NC}"
  mkdir -p "$(dirname "$DATASET_PATH")"
  vei-rollout --episodes "$ROLLOUT_EPISODES" --seed "$SEED" --output "$DATASET_PATH"
}

has_provider_key() {
  local provider=$1
  case "$provider" in
    openai)
      [[ -n "${OPENAI_API_KEY:-}" ]]
      ;;
    anthropic)
      [[ -n "${ANTHROPIC_API_KEY:-}" ]]
      ;;
    google)
      [[ -n "${GOOGLE_API_KEY:-}${GEMINI_API_KEY:-}" ]]
      ;;
    openrouter)
      [[ -n "${OPENROUTER_API_KEY:-}" ]]
      ;;
    *)
      return 1
      ;;
  esac
}

run_eval() {
  local model=$1
  local provider=$2

  if ! has_provider_key "$provider"; then
    echo "${YELLOW}Skipping $provider/$model (missing API key)${NC}"
    return
  fi

  local safe_model
  safe_model=$(echo "$model" | tr ':/' '_')
  local artifacts_dir="$RUN_DIR/${provider}__${safe_model}"
  mkdir -p "$artifacts_dir"

  echo "${YELLOW}Running $provider/$model...${NC}"

  if vei-llm-test \
      --model "$model" \
      --provider "$provider" \
      --max-steps "$MAX_STEPS" \
      --task "$TASK" \
      --dataset "$DATASET_PATH" \
      --artifacts "$artifacts_dir" \
      > "$artifacts_dir/transcript.json" 2> "$artifacts_dir/stderr.log"; then
    echo "${GREEN}[OK] ${provider}/${model} completed${NC}"
  else
    echo "${RED}[FAIL] ${provider}/${model}${NC} (see $artifacts_dir/stderr.log)"
  fi

    if [ -f "$artifacts_dir/trace.jsonl" ]; then
      if vei-score --artifacts-dir "$artifacts_dir" > "$artifacts_dir/score.json" 2> "$artifacts_dir/score.log"; then
        local success actions
        success=$(jq -r '.success' "$artifacts_dir/score.json" 2>/dev/null || echo "unknown")
        actions=$(jq -r '.costs.actions' "$artifacts_dir/score.json" 2>/dev/null || echo "0")
        tokens=$(jq -r '.costs.tokens // 0' "$artifacts_dir/score.json" 2>/dev/null || echo "0")
        echo "  Score -> success=$success actions=$actions tokens=$tokens"
        if [ "$success" = "true" ] && [ "$tokens" -gt 0 ] && [ -n "${VEI_MAX_TOKENS:-}" ] && [ "$tokens" -gt "$VEI_MAX_TOKENS" ]; then
          echo "  ${YELLOW}Note:${NC} token usage $tokens exceeds VEI_MAX_TOKENS=$VEI_MAX_TOKENS" 
        fi
      else
        echo "  ${YELLOW}Scoring failed${NC} (see $artifacts_dir/score.log)"
      fi
  else
    echo "  ${YELLOW}No trace.jsonl emitted${NC}"
  fi

  echo ""
}

write_summary() {
  local summary_file="$RUN_DIR/summary.txt"
  {
    echo "Multi-Provider Eval Summary"
    echo "Generated: $(date)"
    echo "Task: $TASK"
    echo "Dataset: $DATASET_PATH"
    echo
    echo "Results:"
  } > "$summary_file"

  for spec in "${MODELS[@]}"; do
    IFS=':' read -r model provider <<< "$spec"
    local safe_model
    safe_model=$(echo "$model" | tr ':/' '_')
    local artifacts_dir="$RUN_DIR/${provider}__${safe_model}"

    echo >> "$summary_file"
    echo "$provider/$model:" >> "$summary_file"

    if [ -f "$artifacts_dir/score.json" ]; then
      jq -r '
        "  Success: " + ( .success|tostring )
        , "  Actions: " + ( .costs.actions|tostring )
        , "  Subgoals: citations=" + ( .subgoals.citations|tostring )
            + " approval=" + ( .subgoals.approval|tostring )
            + " email_sent=" + ( .subgoals.email_sent|tostring )
            + " email_parsed=" + ( .subgoals.email_parsed|tostring )
      ' "$artifacts_dir/score.json" >> "$summary_file" 2>/dev/null || {
        echo "  Score parsing failed" >> "$summary_file"
      }

      findings_json=$(jq -c '.policy.findings // []' "$artifacts_dir/score.json" 2>/dev/null || echo "[]")
      if [ "$findings_json" != "[]" ]; then
        echo "  Warnings:" >> "$summary_file"
        echo "$findings_json" | jq -r '.[] | "    - \(.code): \(.message)"' >> "$summary_file" 2>/dev/null
      fi

      if jq -e '.success == true' "$artifacts_dir/score.json" >/dev/null 2>&1; then
        actions=$(jq -r '.costs.actions' "$artifacts_dir/score.json" 2>/dev/null || echo "0")
        if [ "$actions" -gt "$MAX_STEPS" ]; then
          echo "  Note: exceeded configured max steps ($actions > $MAX_STEPS)" >> "$summary_file"
        fi
      fi
    else
      if [ -f "$artifacts_dir/stderr.log" ]; then
        echo "  Status: failed (see stderr.log)" >> "$summary_file"
      else
        echo "  Status: skipped" >> "$summary_file"
      fi
    fi
  done

  echo "${YELLOW}Summary written to:${NC} $summary_file"
  echo
}

# -----------------------------------------------------------------------------
# Execution flow
# -----------------------------------------------------------------------------
require_command jq
require_command vei-llm-test
require_command vei-score
require_command vei-rollout

echo "${YELLOW}Starting multi-provider eval...${NC}"
echo " Seed:      $SEED"
echo " Episodes:  $ROLLOUT_EPISODES"
echo " Dataset:   $DATASET_PATH"
echo " Max steps: $MAX_STEPS"
echo " Artifacts: $RUN_DIR"
echo ""

mkdir -p "$RUN_DIR"
ensure_dataset
echo ""

for spec in "${MODELS[@]}"; do
  IFS=':' read -r model provider <<< "$spec"
  run_eval "$model" "$provider"
done

write_summary

echo "${GREEN}Eval complete!${NC} Results saved under $RUN_DIR"
