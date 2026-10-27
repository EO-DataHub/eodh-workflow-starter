# Checks, from fastest to slowest. `make check` must pass before every commit; `make check-docker`
# before calling a change done. See AGENTS.md.

export PYTHONPATH := src
IMAGE = $(shell uv run --quiet python scripts/versions.py image)
WORKFLOW_ID = $(shell uv run --quiet python scripts/versions.py workflow-id)
FIXTURE ?= tests/fixtures/input_item.json

.PHONY: install lint format test validate-cwl check fixture run image check-docker bump versions helpers-checksum clean

install:  ## Install dependencies and the pre-commit hooks
	uv sync
	uv run pre-commit install

lint:  ## Level 1: ruff lint and format check
	uv run ruff check .
	uv run ruff format --check .

format:  ## Fix lint and formatting where ruff can
	uv run ruff check --fix .
	uv run ruff format .

test:  ## Levels 2 and 3: unit tests and the offline end-to-end run
	uv run pytest

validate-cwl:  ## Level 4: cwltool --validate on every CWL file
	for cwl in cwl/*.cwl; do uv run cwltool --validate "$$cwl" || exit 1; done

check: lint test validate-cwl  ## Levels 1-4
	uv run python scripts/versions.py check

fixture:  ## Write a stage-in directory for the fixture item to build/staged
	rm -rf build/staged
	uv run python -m eodh_workflow stage $(FIXTURE) build/staged

run: fixture  ## Run src/main.py on the fixture, without Docker, into build/out
	rm -rf build/out
	uv run python src/main.py --stac_item_dir=build/staged --output_dir=build/out
	uv run python -m eodh_workflow validate build/out

image:  ## Build the linux/amd64 image with the tag in the CWL dockerPull
	docker buildx build --platform linux/amd64 --load -t $(IMAGE) .

check-docker: image fixture  ## Level 5: run the CWL in the image through cwltool, as a non-root user, and validate
	rm -rf build/cwl-out
	uv run cwltool --outdir build/cwl-out cwl/workflow.cwl#$(WORKFLOW_ID) --stac_item build/staged
	uv run python -m eodh_workflow validate "$$(find build/cwl-out -mindepth 1 -maxdepth 1 -type d | head -n 1)"

bump:  ## Set the workflow version everywhere: make bump VERSION=x.y.z
	@test -n "$(VERSION)" || (echo "usage: make bump VERSION=x.y.z" && exit 1)
	uv run python scripts/versions.py bump $(VERSION)
	uv lock

versions:  ## Show the workflow version in each place it is set
	uv run python scripts/versions.py check

helpers-checksum:  ## Template maintainers only: record the checksum of src/eodh_workflow/
	uv run python -m eodh_workflow checksum --write

clean:
	rm -rf build .pytest_cache .ruff_cache

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'
