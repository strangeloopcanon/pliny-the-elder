SHELL := /bin/bash
PYTHON ?= python3.11
VENV ?= .venv
SETUP_STAMP := $(VENV)/.setup-complete
VENV_BIN := $(VENV)/bin
DEPS := black==24.8.0 ruff==0.6.8 mypy==1.11.2 bandit==1.7.9 detect-secrets==1.5.0 pip-audit==2.7.3

.PHONY: setup bootstrap check test llm-live deps-audit all clean

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)

$(SETUP_STAMP): $(VENV)/bin/activate pyproject.toml
	. $(VENV)/bin/activate && \
		pip install --upgrade pip setuptools wheel && \
		pip install -e ".[llm,sse]" && \
		pip install $(DEPS)
	@touch $(SETUP_STAMP)

setup bootstrap: $(SETUP_STAMP)
	@echo "Virtual environment ready at $(VENV)"

check: $(SETUP_STAMP)
	@NEW_PY=$$(git status --short --untracked-files=all -- '*.py' | awk '/^\?\?/ || /^A/{print $$2}'); \
	if [ -n "$$NEW_PY" ]; then \
		echo "Running black on: $$NEW_PY"; \
		. $(VENV)/bin/activate && black --check $$NEW_PY; \
	else \
		echo "No new Python files detected; skipping black."; \
	fi
	@if git status --short --untracked-files=all -- '*.py' | awk '/^\?\?/ || /^A/{print $$2}' | grep -q .; then \
		NEW_PY=$$(git status --short --untracked-files=all -- '*.py' | awk '/^\?\?/ || /^A/{print $$2}'); \
		echo "Running ruff on: $$NEW_PY"; \
		. $(VENV)/bin/activate && ruff check $$NEW_PY; \
	else \
		echo "No new Python files detected; skipping ruff."; \
	fi
	. $(VENV)/bin/activate && mypy vei/router/identity.py vei/router/tool_providers.py vei/identity
	. $(VENV)/bin/activate && bandit -q -r vei
	@mkdir -p .artifacts
	. $(VENV)/bin/activate && detect-secrets scan --all-files --exclude-files '(\\.venv|_vei_out|\\.artifacts|vei\\.egg-info)' > .artifacts/detect-secrets.json

test: $(SETUP_STAMP)
	. $(VENV)/bin/activate && pytest

llm-live: $(SETUP_STAMP)
	@if [ -n "$$VEI_LLM_LIVE_BYPASS" ]; then \
		echo "VEI_LLM_LIVE_BYPASS=1 set; skipping llm-live checks."; \
		exit 0; \
	fi
	@if [ -z "$$OPENAI_API_KEY" ]; then \
		echo "OPENAI_API_KEY not set; cannot run llm-live target. Set the key or export VEI_LLM_LIVE_BYPASS=1 to skip in CI."; \
		exit 4; \
	fi
	. $(VENV)/bin/activate && \
		VEI_SCENARIO=$${VEI_SCENARIO:-multi_channel} \
		vei-llm-test --provider openai --model $${VEI_LLM_MODEL:-gpt-5} --max-steps $${VEI_LLM_MAX_STEPS:-12} --task "$${VEI_LLM_TASK:-Baseline procurement workflow with identity checks.}"

deps-audit: $(SETUP_STAMP)
	. $(VENV)/bin/activate && pip-audit --skip-editable || true

all: check test llm-live deps-audit

clean:
	rm -rf $(VENV) $(SETUP_STAMP)
