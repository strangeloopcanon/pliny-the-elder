#!/usr/bin/env bash
# Frontier Model Evaluation Runner
# Runs comprehensive frontier evaluations across multiple models and providers

set -e

# Configuration
ARTIFACTS_ROOT="${VEI_ARTIFACTS_DIR:-_vei_out/frontier_eval}"
SEED="${VEI_SEED:-42042}"
MAX_STEPS="${VEI_MAX_STEPS:-80}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RUN_ID="frontier_${TIMESTAMP}"

# Models to test (customize as needed)
MODELS_OPENAI="gpt-5 gpt-5-codex"
MODELS_ANTHROPIC="claude-sonnet-4-5 claude-opus-4-1"
MODELS_GOOGLE="models/gemini-2.5-pro models/gemini-2.5-flash"
MODELS_OPENROUTER="x-ai/grok-4"

# Scenario sets
SCENARIO_SET="${1:-all_frontier}"

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║             VEI Frontier Model Evaluation Suite                   ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Run ID: $RUN_ID"
echo "Scenario Set: $SCENARIO_SET"
echo "Max Steps: $MAX_STEPS"
echo "Seed: $SEED"
echo "Artifacts: $ARTIFACTS_ROOT"
echo ""

# Check for API keys
has_openai=false
has_anthropic=false
has_google=false
has_openrouter=false

[[ -n "$OPENAI_API_KEY" ]] && has_openai=true
[[ -n "$ANTHROPIC_API_KEY" ]] && has_anthropic=true
[[ -n "$GOOGLE_API_KEY" || -n "$GEMINI_API_KEY" ]] && has_google=true
[[ -n "$OPENROUTER_API_KEY" ]] && has_openrouter=true

echo "API Keys Available:"
echo "  OpenAI:     $($has_openai && echo '✓' || echo '✗')"
echo "  Anthropic:  $($has_anthropic && echo '✓' || echo '✗')"
echo "  Google:     $($has_google && echo '✓' || echo '✗')"
echo "  OpenRouter: $($has_openrouter && echo '✓' || echo '✗')"
echo ""

if ! ($has_openai || $has_anthropic || $has_google || $has_openrouter); then
    echo "❌ No API keys found. Please set at least one:"
    echo "   export OPENAI_API_KEY=sk-..."
    echo "   export ANTHROPIC_API_KEY=sk-ant-..."
    echo "   export GOOGLE_API_KEY=..."
    echo "   export OPENROUTER_API_KEY=sk-or-..."
    exit 1
fi

# Create run directory
RUN_DIR="$ARTIFACTS_ROOT/$RUN_ID"
mkdir -p "$RUN_DIR"

echo "Starting evaluations..."
echo ""

# Function to run eval for a model
run_eval() {
    local model=$1
    local provider=$2
    
    echo "═══════════════════════════════════════════════════════════════════"
    echo "Evaluating: $model ($provider)"
    echo "═══════════════════════════════════════════════════════════════════"
    
    local model_dir="${RUN_DIR}/${provider}__${model//\//_}"
    mkdir -p "$model_dir"
    
    # Run vei-eval-frontier
    if vei-eval-frontier run \
        --model "$model" \
        --provider "$provider" \
        --scenario-set "$SCENARIO_SET" \
        --max-steps "$MAX_STEPS" \
        --artifacts-root "$model_dir" \
        --seed "$SEED" \
        --verbose; then
        echo "✅ $model completed successfully"
    else
        echo "⚠️  $model failed (continuing...)"
    fi
    
    echo ""
}

# Run OpenAI models
if $has_openai; then
    for model in $MODELS_OPENAI; do
        run_eval "$model" "openai"
    done
fi

# Run Anthropic models
if $has_anthropic; then
    for model in $MODELS_ANTHROPIC; do
        run_eval "$model" "anthropic"
    done
fi

# Run Google models
if $has_google; then
    for model in $MODELS_GOOGLE; do
        run_eval "$model" "google"
    done
fi

# Run OpenRouter models
if $has_openrouter; then
    for model in $MODELS_OPENROUTER; do
        run_eval "$model" "openrouter"
    done
fi

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║                   Generating Reports                               ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Generate comprehensive report
echo "Generating leaderboard..."
vei-report generate \
    --root "$RUN_DIR" \
    --format markdown \
    --output "$RUN_DIR/LEADERBOARD.md"

echo "Generating CSV..."
vei-report generate \
    --root "$RUN_DIR" \
    --format csv \
    --output "$RUN_DIR/results.csv"

echo "Generating JSON..."
vei-report generate \
    --root "$RUN_DIR" \
    --format json \
    --output "$RUN_DIR/results.json"

echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║                      Evaluation Complete                           ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 Results saved to: $RUN_DIR"
echo ""
echo "View results:"
echo "  Leaderboard:  cat $RUN_DIR/LEADERBOARD.md"
echo "  CSV:          open $RUN_DIR/results.csv"
echo "  Summary:      vei-report summary --root $RUN_DIR"
echo ""

# Display quick summary
echo "Quick Summary:"
echo "═══════════════════════════════════════════════════════════════════"
vei-report summary --root "$RUN_DIR"

echo ""
echo "✨ Done!"
