# EODH workflow starter

A template for a workflow that runs on the EO DataHub Workflow Runner and writes STAC outputs that the Hub's map viewer can render.

The example workflow computes NDVI from the red and near-infrared bands of one Sentinel-2 item. It writes a Cloud Optimised GeoTIFF (COG), and a STAC catalog with renders, that pass every check from a unit test to a run of the Docker image through `cwltool`.

To turn your own code into a workflow, give a coding agent [AGENTS.md](AGENTS.md), or follow it yourself. It lists what to decide first, the conversion steps, the rules the Hub depends on, and how to release.

## Start a workflow from the template

Prerequisites:

- [uv](https://docs.astral.sh/uv/)
- Docker with `buildx`, for `make check-docker`

Steps:

1. On GitHub, select **Use this template**, then create the repository in the EO-DataHub organisation.
2. Clone the new repository.
3. Install the dependencies and the pre-commit hooks:

   ```bash
   make install
   ```

4. Run the checks:

   ```bash
   make check
   make check-docker
   ```

5. Follow [AGENTS.md](AGENTS.md) to replace the example with your code.

`make help` lists every command.

## Repository layout

| Path | Contents |
|---|---|
| `src/workflow.py` | The workflow's code. Replace the example with yours. |
| `src/main.py` | The entrypoint that the CWL calls |
| `src/eodh_workflow/` | Helpers. Do not edit them. |
| `cwl/workflow.cwl` | The workflow definition that the Hub runs |
| `tests/` | Tests. `tests/fixtures/input_item.json` is a real input item. |

## Helpers version

The helpers' version is in `src/eodh_workflow/__init__.py`, and changes are in [CHANGELOG.md](CHANGELOG.md). Each version is a tag of this repository.
