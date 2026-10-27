# Changelog

Changes to the helpers in `src/eodh_workflow/` and to the template around them. Each version is a template tag.
To upgrade a workflow, replace `src/eodh_workflow/` and `tests/helpers/` with the ones from the new tag, then make
the changes listed here.

## 0.1.0

First release. The helpers come from `eodh-raster-workflows` 2.0.2.

- `write_outputs`: declarative STAC output, with a collection ID that is unique to each run and renders on the
  collection and on each item.
- `read_staged_item`, `StacItemInput.band()`: read the item that ADES stage-in wrote.
- `write_cog`, `write_cog_chunked`: COG output, in memory or in chunks sized to the container's memory limit.
- `fallback_render`, `remap_source_renders`: renders for outputs that have no fixed render.
- `output_problems`, `python -m eodh_workflow validate`: offline validation of an output directory.
- `stage_item`, `python -m eodh_workflow stage`: a stage-in directory with synthetic rasters for a real item.
