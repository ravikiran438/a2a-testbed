# a2a-testbed monorepo task runner.
# Run `just` (no args) to list every recipe.
# Install Just: https://just.systems  (e.g. `brew install just`).

# Default: list every recipe with its one-line description.
default:
    @just --list --unsorted


# =============================================================================
# Setup
# =============================================================================

# Install dependencies for every app (Python testbed + JS apps).
install:
    @echo "→ Python testbed (editable + test extras)..."
    python3 -m pip install -e ".[test]"
    @echo ""
    @echo "→ Playground (Vite + React + xyflow + ajv) via pnpm..."
    cd playground && pnpm install
    @echo ""
    @echo "→ Cloudflare math agent (Wrangler + types)..."
    cd examples/hosted-agents/cloudflare-math && npm install
    @echo ""
    @echo "✓ All dependencies installed"

# Verify required toolchains are on PATH.
doctor:
    @echo "Checking toolchains..."
    @command -v python3 >/dev/null 2>&1 && echo "  ✓ python3   $$(python3 --version)" || echo "  ✗ python3   missing (required)"
    @command -v node    >/dev/null 2>&1 && echo "  ✓ node      $$(node --version)"    || echo "  ✗ node      missing (required for playground + math agent)"
    @command -v npm     >/dev/null 2>&1 && echo "  ✓ npm       $$(npm --version)"     || echo "  ✗ npm       missing (required for the cloudflare agents)"
    @command -v pnpm    >/dev/null 2>&1 && echo "  ✓ pnpm      $$(pnpm --version)"    || echo "  ✗ pnpm      missing (required for the playground — run 'corepack enable')"
    @command -v go      >/dev/null 2>&1 && echo "  ✓ go        $$(go version | awk '{print $$3}')" || echo "  ○ go        missing (optional, only for Go agent template)"
    @command -v java    >/dev/null 2>&1 && echo "  ✓ java      $$(java -version 2>&1 | head -1 | awk '{print $$3}' | tr -d '\"')" || echo "  ○ java      missing (optional)"
    @command -v wrangler >/dev/null 2>&1 && echo "  ✓ wrangler  $$(wrangler --version 2>&1 | head -1)" || echo "  ○ wrangler  missing (only needed to deploy the cloudflare-math agent)"
    @command -v just    >/dev/null 2>&1 && echo "  ✓ just      $$(just --version)"     || true


# =============================================================================
# Test
# =============================================================================

# Run every test across every app.
test: test-py test-playground

# Python testbed tests (pytest).
test-py:
    @echo "→ Python testbed tests..."
    pytest -q

# Playground TypeScript typecheck.
test-playground:
    @echo "→ Playground typecheck..."
    cd playground && pnpm run typecheck

# Cross-SDK polyglot tests (requires Go / Node.js / Java toolchains on PATH).
test-polyglot:
    @echo "→ Polyglot subprocess tests..."
    pytest -q tests/polyglot/


# =============================================================================
# Build
# =============================================================================

# Build production artifacts for every JS app.
build: build-playground build-math

# Vite production build of the playground.
build-playground:
    @echo "→ Building playground..."
    cd playground && pnpm run build

# Cloudflare-math: typecheck only (Wrangler bundles at deploy time).
build-math:
    @echo "→ Typechecking cloudflare-math worker..."
    cd examples/hosted-agents/cloudflare-math && npm run typecheck


# =============================================================================
# Lint
# =============================================================================

# Lint all JS apps.
lint: lint-playground

lint-playground:
    cd playground && pnpm run lint

# Auto-fix + format the playground with Biome.
format-playground:
    cd playground && pnpm run format


# =============================================================================
# Dev servers
# =============================================================================

# Start the in-browser playground (Vite HMR at http://localhost:5173).
dev:
    cd playground && pnpm run dev

# Start a local cloudflare-math worker (Wrangler at http://localhost:8787).
# Requires .dev.vars with GROQ_API_KEY (see examples/hosted-agents/cloudflare-math/README.md).
math-dev:
    cd examples/hosted-agents/cloudflare-math && npx wrangler dev


# =============================================================================
# Deploy
# =============================================================================

# Deploy the cloudflare-math agent to Cloudflare Workers.
math-deploy:
    cd examples/hosted-agents/cloudflare-math && npx wrangler deploy

# Deploy the cloudflare-task-runner reference agent.
task-runner-deploy:
    cd examples/hosted-agents/cloudflare-task-runner && npx wrangler deploy

# Deploy the cloudflare-push-receiver companion (captures webhooks
# from any agent firing push notifications).
push-receiver-deploy:
    cd examples/hosted-agents/cloudflare-push-receiver && npx wrangler deploy


# =============================================================================
# CLI shortcuts
# =============================================================================

# Run a YAML scenario through the testbed CLI.
#   just run-scenario examples/scenarios/three_party_consent.yaml
run-scenario scenario:
    a2a-testbed run {{scenario}}

# Run the live cloudflare-math demo (requires the worker to be deployed).
math-demo:
    a2a-testbed run examples/scenarios/cloudflare_math_demo.yaml

# Run the live task-runner demo + full transport-contract sweep
# against it (--probe-external). Exercises every A2A 1.0 task /
# streaming / push primitive against the deployed reference agent.
task-runner-demo:
    a2a-testbed run --probe-external examples/scenarios/task_runner_demo.yaml

# Run a2aproject/a2a-tck against the deployed task-runner agent.
# Requires a sibling clone of a2a-tck at ../a2a-tck (override with TCK
# env var) and `uv` on PATH. Treats the task-runner as TCK's SUT —
# two independent verdicts on the same agent (testbed contracts +
# TCK compliance categorization).
tck-against-task-runner tck="../a2a-tck":
    cd "{{tck}}" && \
        (test -d .venv || uv venv) && \
        . .venv/bin/activate && \
        uv pip install -e . >/dev/null && \
        ./run_tck.py --sut-url https://tasks.a2a-testbed.com --category all

# Validate a live agent's AgentCard at the given URL.
#   just card https://my-agent.example.com
card url:
    a2a-testbed card {{url}}

# Run the full A2A 1.0 transport-contract sweep against a deployed agent.
# Standalone — no scenario required. Use this for your own deployments
# (Cloudflare/Lambda/GKE) to confirm wire conformance.
#   just conformance https://my-agent.example.com
conformance url:
    a2a-testbed conformance {{url}}

# Statically validate an AgentCard JSON file (no network).
#   just validate-card path/to/card.json
validate-card card:
    a2a-testbed validate {{card}}

# Generate an ExtensionManifest from a Pydantic Ref class.
#   just gen-manifest https://example.org/my/v1 "My Protocol" 1.0.0 my.types:MyRef ./manifest.json
gen-manifest uri name version ref output:
    a2a-testbed manifest generate \
        --extension-uri {{uri}} \
        --name {{name}} \
        --version {{version}} \
        --ref-class {{ref}} \
        --output {{output}}


# =============================================================================
# Clean
# =============================================================================

# Wipe every build artifact + every node_modules / cache directory.
clean:
    @echo "→ Cleaning JS app artifacts..."
    rm -rf playground/dist playground/node_modules playground/.vite
    rm -rf examples/hosted-agents/cloudflare-math/node_modules
    rm -rf examples/hosted-agents/cloudflare-math/.wrangler
    @echo "→ Cleaning Python caches..."
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
    @echo "✓ Clean"


# =============================================================================
# CI convenience
# =============================================================================

# Reproduce a CI run locally: install + lint + typecheck + test.
ci: install lint test build
    @echo "✓ CI pipeline complete"
