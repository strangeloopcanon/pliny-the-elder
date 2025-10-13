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
ROLLOUT_EPISODES="${VEI_ROLLOUT_EPISODES:-3}"
MAX_STEPS="${VEI_MAX_STEPS:-40}"
TOOL_TOP_K="${VEI_TOOL_TOP_K:-8}"
SCENARIO="${VEI_SCENARIO:-multi_channel}"
TASK="${VEI_TASK:-Procure MacroBook Pro 16 under \$3200, email sales@macrocompute.example for a quote, capture the quote in Docs, create/associate the CRM contact with MacroCompute Inc., log a \$3199 note, and open a delivery ticket.}"

ARTIFACT_ROOT="${VEI_ARTIFACTS_DIR:-_vei_out/llm_eval}"
RUN_STAMP=$(date +%Y%m%d_%H%M%S)
RUN_DIR="$ARTIFACT_ROOT/multi_provider_${RUN_STAMP}"

# Resolve Python interpreter (allows overriding via PYTHON_BIN env var).
if [ -z "${PYTHON_BIN:-}" ]; then
  if command -v pyenv >/dev/null 2>&1; then
    PYENV_PY=$(pyenv which python3 2>/dev/null || pyenv which python 2>/dev/null || true)
    if [ -n "${PYENV_PY:-}" ]; then
      PYTHON_BIN="$PYENV_PY"
    fi
  fi
fi

if [ -z "${PYTHON_BIN:-}" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=$(command -v python3)
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=$(command -v python)
  else
    echo "Python interpreter not found in PATH" >&2
    exit 1
  fi
fi

# Prefer installed console scripts, but fall back to `python -m` invocations.
if command -v vei-llm-test >/dev/null 2>&1; then
  VEI_LLM_TEST_CMD=(vei-llm-test)
else
  VEI_LLM_TEST_CMD=("$PYTHON_BIN" -m vei.cli.vei_llm_test)
fi

if command -v vei-score >/dev/null 2>&1; then
  VEI_SCORE_CMD=(vei-score)
else
  VEI_SCORE_CMD=("$PYTHON_BIN" -m vei.cli.vei_score)
fi

if command -v vei-rollout >/dev/null 2>&1; then
  VEI_ROLLOUT_CMD=(vei-rollout)
else
  VEI_ROLLOUT_CMD=("$PYTHON_BIN" -m vei.cli.vei_rollout)
fi

if command -v vei-eval >/dev/null 2>&1; then
  VEI_EVAL_CMD=(vei-eval)
else
  VEI_EVAL_CMD=("$PYTHON_BIN" -m vei.cli.vei_eval)
fi

# Models to test (model:provider)
declare -a MODELS=(
  "gpt-5:openai"
  "gpt-5-codex:openai"
  "claude-sonnet-4-5:anthropic"
  "x-ai/grok-4:openrouter"
  "models/gemini-2.5-pro:google"
)

if [ -n "${VEI_MODELS:-}" ]; then
  MODELS=()
  while IFS= read -r line; do
    if [ -n "$line" ]; then
      MODELS+=("$line")
    fi
  done <<EOF
$(printf '%s' "$VEI_MODELS" | tr ',' '\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e '/^$/d')
EOF
fi

SCENARIOS=("$SCENARIO")
if [ -n "${VEI_SCENARIOS:-}" ]; then
  SCENARIOS=()
  while IFS= read -r line; do
    if [ -n "$line" ]; then
      SCENARIOS+=("$line")
    fi
  done <<EOF
$(printf '%s' "$VEI_SCENARIOS" | tr ',' '\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e '/^$/d')
EOF
fi

BASELINES=()
BASELINES_RAW="${VEI_BASELINES:-scripted}"
if [ -n "$BASELINES_RAW" ]; then
  lower_baseline=$(printf '%s' "$BASELINES_RAW" | tr '[:upper:]' '[:lower:]')
  if [ "$lower_baseline" != "none" ]; then
    while IFS= read -r line; do
      if [ -n "$line" ]; then
        BASELINES+=("$line")
      fi
    done <<EOF
$(printf '%s' "$BASELINES_RAW" | tr ',' '\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e '/^$/d')
EOF
  fi
fi

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
slugify() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -c '[:alnum:]' '_' | sed -e 's/_\+/_/g' -e 's/^_//' -e 's/_$//'
}

dataset_path_for() {
  local scenario_slug=$1
  if [ -n "${VEI_DATASET:-}" ]; then
    printf '%s\n' "$VEI_DATASET"
  else
    printf "_vei_out/datasets/%s_seed%s.json\n" "$scenario_slug" "$SEED"
  fi
}

require_command() {
  local cmd=$1
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "${RED}ERROR:${NC} Required command '$cmd' not found in PATH" >&2
    exit 1
  fi
}

ensure_dataset() {
  local dataset_path=$1
  if [ -f "$dataset_path" ]; then
    echo "${YELLOW}Dataset already present:${NC} $dataset_path"
    return
  fi

  echo "${YELLOW}Generating dataset with vei-rollout...${NC}"
  mkdir -p "$(dirname "$dataset_path")"
  "${VEI_ROLLOUT_CMD[@]}" \
    --episodes "$ROLLOUT_EPISODES" \
    --seed "$SEED" \
    --output "$dataset_path"
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
  local dataset_path=$3
  local scenario_name=$4
  local scenario_dir=$5

  if ! has_provider_key "$provider"; then
    echo "${YELLOW}Skipping $provider/$model (missing API key)${NC}"
    return
  fi

  local safe_model
  safe_model=$(echo "$model" | tr ':/' '_')
  local artifacts_dir="$scenario_dir/${provider}__${safe_model}"
  mkdir -p "$artifacts_dir"

  echo "${YELLOW}Running $provider/$model...${NC}"

  if VEI_SCENARIO="$scenario_name" \
      OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
      ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
      GOOGLE_API_KEY="${GOOGLE_API_KEY:-}" \
      GEMINI_API_KEY="${GEMINI_API_KEY:-}" \
      OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}" \
      "${VEI_LLM_TEST_CMD[@]}" \
      --model "$model" \
      --provider "$provider" \
      --max-steps "$MAX_STEPS" \
      --task "$TASK" \
      --dataset "$dataset_path" \
      --tool-top-k "$TOOL_TOP_K" \
      --artifacts "$artifacts_dir" \
      > "$artifacts_dir/transcript.json" 2> "$artifacts_dir/stderr.log"; then
    echo "${GREEN}[OK] ${provider}/${model} completed${NC}"
  else
    echo "${RED}[FAIL] ${provider}/${model}${NC} (see $artifacts_dir/stderr.log)"
  fi

  if [ -f "$artifacts_dir/trace.jsonl" ]; then
    if "${VEI_SCORE_CMD[@]}" --artifacts-dir "$artifacts_dir" > "$artifacts_dir/score.json" 2> "$artifacts_dir/score.log"; then
      local success actions tokens
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

run_baseline() {
  local baseline=$1
  local scenario_name=$2
  local dataset_path=$3
  local scenario_dir=$4

  local baseline_slug baseline_dir label
  baseline_slug=$(slugify "$baseline")
  baseline_dir="$scenario_dir/baseline_${baseline_slug}"
  mkdir -p "$baseline_dir"
  label="$baseline"

  echo "${YELLOW}Running baseline ($baseline)...${NC}"

  case "$baseline" in
    scripted)
      if VEI_SCENARIO="$scenario_name" \
          "${VEI_EVAL_CMD[@]}" scripted \
          --seed "$SEED" \
          --dataset "$dataset_path" \
          --artifacts "$baseline_dir" \
          > "$baseline_dir/stdout.log" 2> "$baseline_dir/stderr.log"; then
        echo "${GREEN}[OK] baseline scripted${NC}"
      else
        echo "${RED}[FAIL] baseline scripted${NC} (see $baseline_dir/stderr.log)"
      fi
      ;;
    bc:*)
      local model_path=${baseline#bc:}
      if [ -z "$model_path" ]; then
        echo "${YELLOW}Skipping bc baseline (no model path supplied)${NC}"
        return
      fi
      if [ ! -f "$model_path" ]; then
        echo "${YELLOW}Skipping bc baseline (model not found): $model_path${NC}"
        return
      fi
      if VEI_SCENARIO="$scenario_name" \
          "${VEI_EVAL_CMD[@]}" bc \
          --model "$model_path" \
          --seed "$SEED" \
          --dataset "$dataset_path" \
          --artifacts "$baseline_dir" \
          > "$baseline_dir/stdout.log" 2> "$baseline_dir/stderr.log"; then
        echo "${GREEN}[OK] baseline bc ($model_path)${NC}"
      else
        echo "${RED}[FAIL] baseline bc ($model_path)${NC} (see $baseline_dir/stderr.log)"
      fi
      ;;
    *)
      echo "${YELLOW}Unknown baseline '$baseline' (skipping)${NC}"
      ;;
  esac
}

write_summary() {
  local scenario_name=$1
  local scenario_dir=$2
  local dataset_path=$3
  local summary_file="$scenario_dir/summary.txt"
  {
    echo "Multi-Provider Eval Summary (${scenario_name})"
    echo "Generated: $(date)"
    echo "Task: $TASK"
    echo "Dataset: $dataset_path"
    echo
    echo "Results:"
  } > "$summary_file"

  if [ ${#BASELINES[@]} -gt 0 ]; then
    echo "Baselines:" >> "$summary_file"
    for baseline in "${BASELINES[@]}"; do
      local baseline_slug
      baseline_slug=$(slugify "$baseline")
      local baseline_dir="$scenario_dir/baseline_${baseline_slug}"
      echo "  $baseline:" >> "$summary_file"
      if [ -f "$baseline_dir/score.json" ]; then
        jq -r '
          "    Success: " + ( .success|tostring )
          , "    Actions: " + ( .costs.actions|tostring )
          , "    Subgoals: citations=" + ( .subgoals.citations|tostring )
              + " approval=" + ( .subgoals.approval|tostring )
              + " approval_with_amount=" + ( .subgoals.approval_with_amount|tostring )
              + " email_sent=" + ( .subgoals.email_sent|tostring )
              + " email_parsed=" + ( .subgoals.email_parsed|tostring )
          , "             doc_logged=" + ( .subgoals.doc_logged|tostring )
              + " ticket_updated=" + ( .subgoals.ticket_updated|tostring )
              + " crm_logged=" + ( .subgoals.crm_logged|tostring )
          , "    Time_ms: " + ( .costs.time_ms|tostring )
          , "    Tokens: " + (( .costs.tokens // 0 )|tostring )
          , "    Policy: warnings=" + ( .policy.warning_count|tostring )
              + " errors=" + ( .policy.error_count|tostring )
          , "    Top tools: " + (
              ( .usage
                | to_entries
                | sort_by(-.value)
                | map(.key + ":" + (.value|tostring))
                | .[0:3]
                | join(", " )
              ) // "n/a"
            )
        ' "$baseline_dir/score.json" >> "$summary_file" 2>/dev/null || {
          echo "    Summary parsing failed" >> "$summary_file"
        }
      else
        if [ -f "$baseline_dir/stderr.log" ]; then
          echo "    Status: failed (see baseline_${baseline_slug}/stderr.log)" >> "$summary_file"
        else
          echo "    Status: not run" >> "$summary_file"
        fi
      fi
    done
    echo >> "$summary_file"
  fi

  for spec in "${MODELS[@]}"; do
    IFS=':' read -r model provider <<< "$spec"
    local safe_model
    safe_model=$(echo "$model" | tr ':/' '_')
    local artifacts_dir="$scenario_dir/${provider}__${safe_model}"

    echo >> "$summary_file"
    echo "$provider/$model:" >> "$summary_file"

    if [ -f "$artifacts_dir/score.json" ]; then
      jq -r '
        "  Success: " + ( .success|tostring )
        , "  Actions: " + ( .costs.actions|tostring )
        , "  Subgoals: citations=" + ( .subgoals.citations|tostring )
            + " approval=" + ( .subgoals.approval|tostring )
            + " approval_with_amount=" + ( .subgoals.approval_with_amount|tostring )
            + " email_sent=" + ( .subgoals.email_sent|tostring )
            + " email_parsed=" + ( .subgoals.email_parsed|tostring )
        , "             doc_logged=" + ( .subgoals.doc_logged|tostring )
            + " ticket_updated=" + ( .subgoals.ticket_updated|tostring )
            + " crm_logged=" + ( .subgoals.crm_logged|tostring )
        , "  Time_ms: " + ( .costs.time_ms|tostring )
        , "  Tokens: " + (( .costs.tokens // 0 )|tostring )
        , "  Policy: warnings=" + ( .policy.warning_count|tostring )
            + " errors=" + ( .policy.error_count|tostring )
        , "  Top tools: " + (
            ( .usage
              | to_entries
              | sort_by(-.value)
              | map(.key + ":" + (.value|tostring))
              | .[0:3]
              | join(", " )
            ) // "n/a"
          )
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

echo "${YELLOW}Starting multi-provider eval...${NC}"
echo " Seed:      $SEED"
echo " Episodes:  $ROLLOUT_EPISODES"
echo " Scenarios: ${SCENARIOS[*]}"
echo " Models:    ${MODELS[*]}"
if [ ${#BASELINES[@]} -gt 0 ]; then
  echo " Baselines: ${BASELINES[*]}"
else
  echo " Baselines: none"
fi
echo " Max steps: $MAX_STEPS"
echo " Artifacts: $RUN_DIR"
echo " Python:    $PYTHON_BIN"
echo ""

mkdir -p "$RUN_DIR"
for scenario_name in "${SCENARIOS[@]}"; do
  scenario_slug=$(slugify "$scenario_name")
  scenario_dir="$RUN_DIR/$scenario_slug"
  mkdir -p "$scenario_dir"

  dataset_path=$(dataset_path_for "$scenario_slug")

  echo "${YELLOW}Scenario:${NC} $scenario_name (slug: $scenario_slug)"
  ensure_dataset "$dataset_path"
  echo ""

  if [ ${#BASELINES[@]} -gt 0 ]; then
    for baseline in "${BASELINES[@]}"; do
      run_baseline "$baseline" "$scenario_name" "$dataset_path" "$scenario_dir"
    done
    echo ""
  fi

  for spec in "${MODELS[@]}"; do
    IFS=':' read -r model provider <<< "$spec"
    run_eval "$model" "$provider" "$dataset_path" "$scenario_name" "$scenario_dir"
  done

  write_summary "$scenario_name" "$scenario_dir" "$dataset_path"
done

echo "${GREEN}Eval complete!${NC} Results saved under $RUN_DIR"
