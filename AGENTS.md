# AGENTS.md

This file tells a coding agent how to turn a Python script or project into a workflow for the EO DataHub (EODH) Workflow Runner (ADES). The workflow must run on the Hub and write STAC outputs that the Hub's map viewer can render. Follow it from top to bottom.

## 1. What this repository is

A template for one workflow. It has a working example, NDVI from one STAC item, that passes every check below.

| Path | What it is | Who edits it |
|---|---|---|
| `src/workflow.py` | `run(inputs, output_dir) -> OutputSpec`. The workflow's own code. | You |
| `src/*.py` (other files) | Extra modules that `workflow.py` imports | You |
| `src/main.py` | Entrypoint that the CWL calls. Reads the inputs, calls `run()`, writes the STAC. | Nobody |
| `src/eodh_workflow/` | Helpers: stage-in reader, STAC writer, COG writer, memory, validation, test helpers | Nobody |
| `cwl/workflow.cwl` | The workflow definition the Hub runs | You |
| `tests/fixtures/input_item.json` | One real STAC item from the input collection | You |
| `tests/test_*.py` | Tests for your workflow | You |
| `tests/helpers/` | Tests for the helpers | Nobody |
| `Dockerfile`, `Makefile`, `scripts/`, `.github/` | Build, checks and release | Only when a step below says so |

**Do not edit `src/eodh_workflow/` or `src/main.py`.** A test compares `src/eodh_workflow/` with its recorded checksum, so CI fails on any edit. If the helpers cannot do something you need, use the escape hatches in step 3. If those are not enough, stop and tell the human what is missing.

The helpers' version is `eodh_workflow.__version__`. To upgrade the helpers, replace `src/eodh_workflow/` and `tests/helpers/` with the ones from a newer template tag, then read `CHANGELOG.md` for changes.

## 2. Before you start

Ask the human these questions. Do not guess the answers. Write them down in the pull request description.

1. **Input mode.** Which of these does the workflow use?
   - **Stage-in**: the job gives one STAC item, and ADES downloads the item and its assets before the tool runs.
   - **Fetch**: the job gives strings (URLs, IDs, dates), and the tool downloads its own data.
2. **Input collection.** Which STAC collection do the input items come from? Ask for the URL of one real item from it.
3. **Outputs.** Which files does one run produce? For each one: raster or not, how many bands, data type, and nodata value.
4. **Renders.** For each raster output: which bands to show, the value range to stretch (`rescale`), and the colour map. If the human does not know, use `fallback_render` (a 2nd–98th percentile stretch) and say so.
5. **Names and limits.**
   - The workflow ID, for example `water-mask`.
   - The image name. The default is `ghcr.io/eo-datahub/<repository name>`, in lower case.
   - The memory (`ramMax`, MiB) and CPU (`coresMax`) the tool needs.

If an answer needs something in [Not supported](#5-not-supported), stop and tell the human. Do not build a workaround.

## 3. Convert the code

Do the steps in order. Each step has one action.

### Step 1: Write `run()`

Replace `src/workflow.py` with the human's code. Keep this signature:

```python
def run(inputs: WorkflowInputs, output_dir: Path) -> OutputSpec: ...
```

`inputs` has two fields:

- `inputs.stac_item` is the staged item (`StacItemInput`), or `None` in fetch mode.
- `inputs.params` is a `dict` of every other CWL input, as strings. Optional inputs that the job left out are not in it.

Use these to read the staged item:

| Call | Returns |
|---|---|
| `inputs.stac_item.band("red")` | `Band(path, index)` for the band with that STAC common name. Works for one-asset-per-band items and for multi-band assets. |
| `inputs.stac_item.asset_path("cog")` | Local path of an asset |
| `inputs.stac_item.item` | The item JSON as a `dict` |

Write every output file under `output_dir`, and nowhere else. Write rasters with one of these:

- `write_cog_chunked(bands, path, fn)` reads the input bands in chunks, calls `fn(*arrays)` on each chunk, and writes a COG. The chunk size comes from the container's memory limit. Use it for any input that can be large.
- `write_cog(path, array, crs, transform, nodata)` writes an array that is already in memory.

For float outputs, use NaN as nodata. For integer outputs, use a nodata value that is not a valid data value.

If the human's code is not Python, stop and tell the human. A two-step CWL for non-Python tools is not in this version.

### Step 2: Return an `OutputSpec`

`run()` returns what it wrote. The helpers compute the rest of the metadata: footprint, extent, projection, bands and statistics, datetimes, and the catalog layout.

```python
return OutputSpec(
    collection=CollectionSpec(
        id="ndvi",  # catalog ID, the same for every run
        title="NDVI",
        description="...",
        keywords=["ndvi"],
        renders={"ndvi": {"title": "NDVI", "assets": ["data"], "rescale": [[-1, 1]], "colormap_name": "rdylgn"}},
    ),
    items=[
        ItemSpec(
            id=f"{item.id}_ndvi",
            source_item=item,  # the input item: datetime, platform and licence come from it
            assets={
                "data": RasterAsset(cog, bands=[{"name": "ndvi"}]),
                "table": FileAsset(csv, "text/csv"),
            },
            extra_properties={"ndvi:threshold": 0.3},
        )
    ],
)
```

- Use the asset key `data` for the main raster.
- Set `source_item` whenever the data came from a STAC item, in fetch mode too.
- An item with no raster asset needs `geometry`.
- Render colour maps are the [titiler colour map names](https://developmentseed.org/titiler/advanced/rendering/).

`write_outputs` refuses output the Hub cannot use. It lists every problem in one `OutputError`. It refuses:

- a raster that is not a COG with overviews;
- raster assets with no renders;
- a render without `rescale`;
- a render that uses an asset an item does not have, or a non-raster asset;
- a file outside `output_dir`, or a file in `output_dir` that no asset references.

If the specs cannot express something, use the escape hatches in this order:

1. `extra_properties` on `ItemSpec`, and `extra_fields` on `CollectionSpec`, `RasterAsset` and `FileAsset`.
2. `OutputSpec(customise=fn)`. `fn(catalog)` gets the pystac catalog before it is saved and validated.

### Step 3: Update the CWL

Edit `cwl/workflow.cwl`:

1. Set the `Workflow` `id` to the workflow ID.
2. Set `label` and `doc`. The Hub shows them to users.
3. Set `ramMax` and `coresMax` on the `CommandLineTool`.
4. Set the `Workflow`-level `ramMax` to at least the tool's `ramMax`.
5. Set the image name in `dockerPull`. Keep the tag; `make bump` sets it.
6. Add one input to the `Workflow` and one to the `CommandLineTool` for each parameter. Connect them in the step's `in`.

Bind each tool input as `--<name>=<value>`, the form `main.py` reads:

```yaml
      threshold:
        type: string?
        inputBinding:
          prefix: --threshold=
          separate: false
```

For fetch mode, make these changes too:

1. Delete the `stac_item` input from the `Workflow`, and `stac_item_dir` from the step and the tool.
2. Add the string inputs, for example `item_url`.
3. Add network access to the tool's `requirements`:

   ```yaml
      - class: NetworkAccess
        networkAccess: true
   ```

4. Edit `check-docker` in the `Makefile`: replace `--stac_item build/staged` with your inputs, for example `--item_url https://...`.

Keep the `$graph` form with one `Workflow` and one `CommandLineTool`. Keep the `results` output with `glob: "."`.

### Step 4: Add dependencies

Add each package the code imports:

```bash
uv add <package>
```

Do not use `pip`. The image installs exactly what is in `uv.lock`. If a package needs a system library, add it to the `apt-get install` line in the `Dockerfile`.

### Step 5: Replace the fixture

1. Download the real item that the human gave you in [section 2](#2-before-you-start). Save it as `tests/fixtures/input_item.json`. Keep the asset hrefs as they are.
2. Run `make fixture`. It writes `build/staged`, a stage-in directory with small synthetic rasters that match the item's band layout.
3. If the synthetic values do not suit the workflow, pass `values={"red": 500, ...}` to `stage_item` in `tests/conftest.py`.

For fetch mode, stage the fixture the same way, and monkeypatch the fetch in the tests. `tests/test_fetch_mode.py` shows how.

### Step 6: Write the tests

1. Replace `tests/test_workflow.py` with unit tests for `run()` and the functions it calls. Check output values, not only that files exist.
2. Keep `tests/test_end_to_end.py`. Change it only if the workflow needs params: add them to the `main.main([...])` call.
3. Delete `tests/test_fetch_mode.py` if the workflow uses stage-in. Keep it as a pattern if the workflow uses fetch mode.

### Step 7: Run `make check`

`make check` runs levels 1 to 4. Fix every failure, then run it again. Do not skip a test or loosen a check to make it pass.

### Step 8: Run `make check-docker`

`make check-docker` runs level 5. It builds the image for `linux/amd64`, runs the CWL through `cwltool` on the fixture as a non-root user, and validates the output.

**The work is not done until `make check-docker` passes.** If Docker is not available, say so to the human. Do not report the work as done.

### Step 9: Give the human the level 6 checklist

Level 6 needs the Hub, so the human does it. Copy this list into your final message:

- [ ] Release the image (see [Release](#7-release)), and make the GHCR package public.
- [ ] Deploy `cwl/workflow.cwl` to a workspace on the Hub.
- [ ] Run a job with a real input item.
- [ ] The job status is `successful`.
- [ ] The job's `/results` link shows a catalog with one collection and the expected items.
- [ ] The map viewer shows each raster with the expected colours.
- [ ] Run a second job. Both collections are still there, with different IDs.

### Checks

| Level | Check | Command | Where it runs |
|---|---|---|---|
| 1 | `ruff` lint and format, at the version pinned in `uv.lock` | `make lint` | pre-commit, CI |
| 2 | Unit tests for `run()` | `make test` | CI |
| 3 | `main.py` on the fixture, then `validate_output_dir`: STAC schemas, render rules, COGs, layout, stray files, and a new collection ID for each run | `make test` | CI |
| 4 | `cwltool --validate` on every CWL file | `make validate-cwl` | CI |
| 5 | The image through `cwltool`, as a non-root user, then the level 3 validation | `make check-docker` | Local; CI on pull requests |
| 6 | A job on the Hub, and the map viewer | Manual | The human |

`make check` runs levels 1 to 4. `make run` runs `main.py` on the fixture without Docker, into `build/out`, which is faster to debug than level 5.

## 4. Hard rules

The helpers and checks enforce these rules. Do not work around them.

| Rule | Reason | Where the platform makes it necessary |
|---|---|---|
| The collection ID is unique to each run. The catalog ID is the same for every run. | Stage-out writes every run of a workflow to `processing-results/<workflow ID>/<catalog ID>/<collection ID>/`. A fixed collection ID makes each run overwrite the last one. | `ades-stageout`, `stageout/__main__.py`, `handle_stac_outputs` |
| Renders go on the collection and on every item, and are the same on both. | titiler's `/renders` endpoint reads item renders. titiler-stacapi reads collection renders. | `titiler`, `titiler-stacapi` |
| Every render has an explicit `rescale`. Band statistics go in `bands`. | The tilers stretch automatically only from `raster:bands` statistics, so a render without `rescale` shows a blank or saturated map. | `titiler`, `titiler-stacapi` |
| Rasters are COGs with internal overviews. | The tilers read tiles and overviews over HTTP. A plain GeoTIFF is slow or fails at low zoom. | `titiler` |
| Memory limits come from the cgroup, not from `psutil`. | In a pod, `psutil` reports the node's free memory. The pod's limit comes from `ramMax`. | `zoo-calrissian-runner`, `get_max_ram` |
| Outputs go only under `output_dir`. | Stage-out uploads the whole output directory, and nothing outside it. | `ades-stageout` |
| Every file in the image is world-readable. | The runner does not run the container as root. | `eodhp-calrissian`; `cwltool` runs with `--user` too |
| The image is built for `linux/amd64`. | The cluster nodes are amd64. An arm64 image from a Mac fails with `exec format error`. | EKS node groups |
| The stage-out collection extent matches the items. | Stage-out uses the collection as it is, and does not recompute the extent. | `ades-stageout`, `handle_current_collection` |

## 5. Not supported

This version does not support these. If the workflow needs one, tell the human and stop.

- More than one input item through stage-in (`Directory[]`).
- Vector outputs that render on the map. You can write vector files as `FileAsset`, but the map viewer does not show them.
- Tools that are not written in Python.
- More than one `CommandLineTool` in the CWL.

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `PermissionError` in the container, on a file in `/app` or the virtual environment. | The image has a file that only root can read. The runner does not run as root. | Keep `chmod -R a+rX /app` in the `Dockerfile`. Do not write files to `/app` at run time; write to `output_dir`. |
| `ImportError: libexpat.so.1: cannot open shared object file` | The rasterio wheel needs `libexpat1`, which `python:*-slim` does not have. | Keep `libexpat1` in the `apt-get install` line. |
| A new run replaced the outputs of an earlier run. | The collection ID is fixed. | Return a `CollectionSpec` and let `write_outputs` make the collection ID. Do not set the collection ID in `customise`. |
| The job succeeds but the map shows nothing, or a grey or white square. | A render is missing, uses the wrong asset key, or has a `rescale` outside the data range. | Check `rescale` against the band `statistics` in the item JSON. Check that the render's `assets` are the raster's asset key. |
| `cwltool`: "Tool file contains graph of multiple objects, must specify one of #..." | A `$graph` file needs the process to run. | Add `#<workflow ID>` to the path: `cwltool cwl/workflow.cwl#<workflow ID> ...`. `make check-docker` does this. |
| `cwltool` pulls the image, or fails to pull it. | The local image tag does not match `dockerPull`. | Run `make image`, which tags the image with the `dockerPull` value. |
| `OutputError: Files in the output directory that no asset references` | `run()` left temporary files in `output_dir`. | Delete them before `run()` returns, or add them as assets. |
| `test_helpers_unchanged` fails. | Something changed `src/eodh_workflow/`. | Undo the change: `git checkout -- src/eodh_workflow`. |

## 7. Release

A workflow has its own version, `x.y.z`. Three places hold it, and they must match:

- `version` in `pyproject.toml`;
- `s:softwareVersion` in `cwl/workflow.cwl`;
- the `dockerPull` tag in `cwl/workflow.cwl`.

`make versions` shows all three. `make bump VERSION=x.y.z` sets all three.

### Release with GitHub Actions

1. Run `make bump VERSION=x.y.z`.
2. Commit the change and merge it to `main`.
3. Tag the merge commit: `git tag vx.y.z`.
4. Push the tag: `git push origin vx.y.z`.

`.github/workflows/release.yml` then does this:

1. Checks that the three versions and the tag match.
2. Checks that `dockerPull` is `ghcr.io/<owner>/<repository>`, in lower case.
3. Runs `make check` and `make check-docker`.
4. Pushes the image to GHCR.

After the first release, make the package public. GHCR packages are private by default, and ADES pulls images without credentials.

1. Open the repository on GitHub and select **Packages**, then the package.
2. Select **Package settings**.
3. Under **Danger Zone**, select **Change visibility**, then **Public**.

### Release by hand

Use this if GitHub Actions cannot push to GHCR.

1. Run `make bump VERSION=x.y.z`.
2. Run `make check`.
3. Run `make check-docker`.
4. Log in to the registry: `echo $GITHUB_TOKEN | docker login ghcr.io -u <user> --password-stdin`. The token needs the `write:packages` scope.
5. Push the image: `docker buildx build --platform linux/amd64 --push -t "$(uv run python scripts/versions.py image)" .`
6. Make the package public, as above.

### Release to Amazon ECR Public

Use this if the Hub deployment cannot pull from GHCR.

1. Change the image name in `dockerPull` to `public.ecr.aws/<alias>/<name>`.
2. Log in: `aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws`.
3. Do steps 1 to 5 of [Release by hand](#release-by-hand).
4. Delete the GHCR login and push steps from `.github/workflows/release.yml`, or add an ECR login step in their place.

ECR Public repositories are public, so you do not need to change their visibility.

### Deploy

Push the image before you deploy the CWL. The CWL names the image tag, so a CWL deployed before its image is pushed fails on the Hub.
