#!/bin/bash
# Multi-provider eval script for VEI
# Tests OpenAI, Anthropic, and Google Gemini providers

set -e  # Exit on error

# Load .env file if it exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Base output directory
EVAL_DIR="evals/multi_provider_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$EVAL_DIR"

echo -e "${YELLOW}Starting multi-provider eval...${NC}"
echo "Results will be saved to: $EVAL_DIR"
echo ""

# Check for API keys
if [ -z "$OPENAI_API_KEY" ]; then
    echo -e "${RED}ERROR: OPENAI_API_KEY not set${NC}"
    exit 1
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo -e "${YELLOW}WARNING: ANTHROPIC_API_KEY not set, skipping Anthropic models${NC}"
fi

if [ -z "$GOOGLE_API_KEY" ] && [ -z "$GEMINI_API_KEY" ]; then
    echo -e "${YELLOW}WARNING: GOOGLE_API_KEY/GEMINI_API_KEY not set, skipping Google models${NC}"
fi

if [ -z "$OPENROUTER_API_KEY" ]; then
    echo -e "${YELLOW}WARNING: OPENROUTER_API_KEY not set, skipping OpenRouter models${NC}"
fi

# Default task
TASK="Research MacroBook Pro 16 specs from vweb.local/pdp/macrobook-pro-16, get Slack approval with budget < \$3200, email vendor sales@macrocompute.example for price and ETA."

# Models to test - LATEST frontier models only
declare -a MODELS=(
    "gpt-5:openai"
    "gpt-5-codex:openai"
    "x-ai/grok-4:openrouter"
    "claude-sonnet-4-5:anthropic"
    "models/gemini-2.5-flash:google"
)

# Function to run eval for a model
run_eval() {
    local model=$1
    local provider=$2
    local model_safe=$(echo "$model" | tr ':/' '_')
    local artifacts_dir="$EVAL_DIR/${provider}__${model_safe}"
    
    echo -e "${YELLOW}Testing $provider/$model...${NC}"
    
    # Check if provider key is set
    if [ "$provider" = "anthropic" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
        echo -e "${YELLOW}Skipping $model (no API key)${NC}"
        return
    fi
    
    if [ "$provider" = "google" ] && [ -z "$GOOGLE_API_KEY" ] && [ -z "$GEMINI_API_KEY" ]; then
        echo -e "${YELLOW}Skipping $model (no API key)${NC}"
        return
    fi
    
    if [ "$provider" = "openrouter" ] && [ -z "$OPENROUTER_API_KEY" ]; then
        echo -e "${YELLOW}Skipping $model (no API key)${NC}"
        return
    fi
    
    mkdir -p "$artifacts_dir"
    
    # Run the eval
    if python -m vei.cli.vei_llm_test \
        --model "$model" \
        --provider "$provider" \
        --max-steps 12 \
        --task "$TASK" \
        --artifacts "$artifacts_dir" \
        > "$artifacts_dir/transcript.json" 2> "$artifacts_dir/stderr.log"; then
        
        echo -e "${GREEN}✓ $model completed${NC}"
        
        # Run scoring if trace exists
        if [ -f "$artifacts_dir/trace.jsonl" ]; then
            python -m vei.cli.vei_score --artifacts-dir "$artifacts_dir" > "$artifacts_dir/score.json" 2>&1
            
            # Extract key metrics
            if [ -f "$artifacts_dir/score.json" ]; then
                success=$(jq -r '.success' "$artifacts_dir/score.json" 2>/dev/null || echo "unknown")
                actions=$(jq -r '.costs.actions' "$artifacts_dir/score.json" 2>/dev/null || echo "0")
                echo "  Success: $success | Actions: $actions"
            fi
        else
            echo -e "${YELLOW}  No trace.jsonl generated${NC}"
        fi
    else
        echo -e "${RED}✗ $model failed${NC}"
        echo "  See $artifacts_dir/stderr.log for details"
    fi
    
    echo ""
}

# Run evals for all models
for model_spec in "${MODELS[@]}"; do
    IFS=':' read -r model provider <<< "$model_spec"
    run_eval "$model" "$provider"
done

# Generate summary
echo -e "${YELLOW}Generating summary...${NC}"
SUMMARY_FILE="$EVAL_DIR/summary.txt"

cat > "$SUMMARY_FILE" << EOF
Multi-Provider Eval Summary
Generated: $(date)
Task: $TASK

Results:
EOF

for model_spec in "${MODELS[@]}"; do
    IFS=':' read -r model provider <<< "$model_spec"
    model_safe=$(echo "$model" | tr ':/' '_')
    artifacts_dir="$EVAL_DIR/${provider}__${model_safe}"
    
    if [ -f "$artifacts_dir/score.json" ]; then
        success=$(jq -r '.success' "$artifacts_dir/score.json" 2>/dev/null || echo "unknown")
        actions=$(jq -r '.costs.actions' "$artifacts_dir/score.json" 2>/dev/null || echo "0")
        citations=$(jq -r '.subgoals.citations' "$artifacts_dir/score.json" 2>/dev/null || echo "0")
        approval=$(jq -r '.subgoals.approval' "$artifacts_dir/score.json" 2>/dev/null || echo "0")
        email_sent=$(jq -r '.subgoals.email_sent' "$artifacts_dir/score.json" 2>/dev/null || echo "0")
        email_parsed=$(jq -r '.subgoals.email_parsed' "$artifacts_dir/score.json" 2>/dev/null || echo "0")
        
        cat >> "$SUMMARY_FILE" << EOF

$provider/$model:
  Success: $success
  Actions: $actions
  Subgoals: citations=$citations approval=$approval email_sent=$email_sent email_parsed=$email_parsed
EOF
    else
        cat >> "$SUMMARY_FILE" << EOF

$provider/$model:
  Status: Failed or no score generated
EOF
    fi
done

cat "$SUMMARY_FILE"
echo ""
echo -e "${GREEN}Eval complete! Results in: $EVAL_DIR${NC}"
