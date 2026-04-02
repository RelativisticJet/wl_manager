#
# Whitelist Manager — Build & Test Commands
#
# This Makefile is the single entry point for all development tasks.
# Run 'make help' to see available targets.
#

APP_NAME    := wl_manager
VERSION     := $(shell grep '^version' default/app.conf | head -1 | cut -d= -f2 | tr -d ' ')
SPL_FILE    := dist/$(APP_NAME)-$(VERSION).spl
SPLUNK_PASS ?= Chang3d!

.PHONY: help validate test package clean docker-up docker-down docker-logs docker-restart metrics metrics-report

help: ## Show this help message
	@echo ""
	@echo "Whitelist Manager — Development Commands"
	@echo "========================================="
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Typical workflow:"
	@echo "  make docker-up     # start Splunk in Docker"
	@echo "  make test          # run integration tests"
	@echo "  make package       # build .spl file"
	@echo ""

# ── Phase 2: Validate ─────────────────────────────────────────────────

validate: ## Run all validation checks (syntax, security, structure)
	@bash scripts/validate.sh

# ── Phase 3: Test in Docker ───────────────────────────────────────────

docker-up: ## Start the containerized Splunk instance
	docker compose up -d
	@echo ""
	@echo "Splunk is starting... (takes ~60-90 seconds)"
	@echo "  Web UI:  http://localhost:8000"
	@echo "  User:    admin"
	@echo "  Pass:    $(SPLUNK_PASS)"
	@echo ""
	@echo "Check progress with: make docker-logs"

docker-down: ## Stop and remove the Splunk container
	docker compose down

docker-clean: ## Stop container AND delete all data volumes
	docker compose down -v

docker-logs: ## Tail Splunk container logs
	docker compose logs -f

docker-restart: ## Restart Splunk inside the container (picks up .conf changes)
	docker exec wl_manager_test /opt/splunk/bin/splunk restart

docker-wait: ## Wait until Splunk is fully ready, then return
	@echo "Waiting for Splunk to be ready..."
	@for i in $$(seq 1 60); do \
		if curl -sk -o /dev/null -w "%{http_code}" \
			-u admin:$(SPLUNK_PASS) \
			https://localhost:8089/services/server/info 2>/dev/null | grep -q 200; then \
			echo "  Splunk is ready!"; \
			exit 0; \
		fi; \
		echo "  Attempt $$i/60 — not ready yet..."; \
		sleep 3; \
	done; \
	echo "  ERROR: Splunk did not start within 3 minutes."; \
	exit 1

test: ## Run integration tests against Docker Splunk
	@bash scripts/test_integration.sh

# ── Quality Metrics ───────────────────────────────────────────────────

metrics: ## Enforce quality gates (CC<15, coverage>=80%, LOC<1000)
	python3 scripts/metrics_collector.py --gate

metrics-report: ## Generate CODE_METRICS.md without enforcing thresholds
	python3 scripts/metrics_collector.py --report

# ── Phase 4: Package ──────────────────────────────────────────────────

package: validate ## Build the .spl file (runs validation first)
	@bash scripts/package.sh

# ── Utilities ─────────────────────────────────────────────────────────

clean: ## Remove build artifacts
	rm -rf dist/
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} +
	@echo "Cleaned."

inspect: ## List contents of the built .spl file
	@if [ -f "$(SPL_FILE)" ]; then \
		echo "Contents of $(SPL_FILE):"; \
		echo ""; \
		tar -tzf "$(SPL_FILE)"; \
	else \
		echo "No .spl file found. Run 'make package' first."; \
	fi

# ── Full Pipeline ─────────────────────────────────────────────────────

all: validate docker-up docker-wait test package ## Run the full pipeline: validate → docker → test → package
	@echo ""
	@echo "Full pipeline completed successfully!"
	@echo "Package: $(SPL_FILE)"
