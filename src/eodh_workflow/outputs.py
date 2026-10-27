"""
Write the output STAC for a run: Catalog -> Collection -> Items, from a declarative spec.

You describe the outputs (`CollectionSpec`, `ItemSpec`, `RasterAsset`, `FileAsset`) and
`write_outputs` computes the metadata: footprint, extent, projection, bands and statistics,
datetimes, and renders on both the Collection and every Item. It refuses output that the Hub
cannot render, and validates what it wrote with `validate_output_dir`.

Layout, relative to the output directory:

    catalog.json
    <collection_id>/collection.json
    <collection_id>/<item_id>/<item_id>.json
    <asset files, wherever run() wrote them under the output directory>

ADES stage-out keeps each asset's path relative to the output root and writes every run of a
workflow under `processing-results/<workflow-id>/<catalog id>/<collection id>/`. The catalog ID
is the same for every run, and the collection ID is unique per run, so runs cannot overwrite
each other. Stage-out uses the Collection as it is and does not recompute its extent.

Renders go on the Collection (read by titiler-stacapi) and on each Item (read by titiler's
`/renders` endpoint).
"""

import copy
import datetime as dt
import logging
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import pystac
import rasterio
from pystac.utils import str_to_datetime
from rasterio.warp import transform_bounds, transform_geom

from .inputs import StacItemInput
from .validate import OutputError, assert_valid_output_dir, cog_problems

logger = logging.getLogger(__name__)

PROJECTION_EXTENSION = "https://stac-extensions.github.io/projection/v2.0.0/schema.json"
RENDER_EXTENSION = "https://stac-extensions.github.io/render/v2.1.0/schema.json"
EO_EXTENSION = "https://stac-extensions.github.io/eo/v2.0.0/schema.json"

# Source item properties carried over to the output items.
COPIED_SOURCE_PROPERTIES = ("platform", "constellation", "instruments", "eo:cloud_cover")
# Points per edge when reprojecting the footprint, so curved edges in EPSG:4326 are followed.
_DENSIFY_POINTS = 21


@dataclass
class RasterAsset:
    """
    A raster file that `run()` wrote under the output directory. It must be a COG.

    `bands` describes each band, in order, for example `[{"name": "ndvi"}]` or
    `[{"name": "B04", "eo:common_name": "red"}]`. `data_type`, `nodata` and `statistics` are
    read from the file. If you leave `bands` out, the bands are named `b1`, `b2`, ...
    """

    path: Path
    bands: Optional[List[dict]] = None
    title: Optional[str] = None
    description: Optional[str] = None
    roles: Sequence[str] = ("data",)
    extra_fields: dict = field(default_factory=dict)


@dataclass
class FileAsset:
    """A non-raster file that `run()` wrote under the output directory, for example a CSV or GeoJSON."""

    path: Path
    media_type: str
    title: Optional[str] = None
    description: Optional[str] = None
    roles: Sequence[str] = ("data",)
    extra_fields: dict = field(default_factory=dict)


Asset = Union[RasterAsset, FileAsset]


@dataclass
class ItemSpec:
    """
    One output item.

    `source_item` is the input item the output was made from. Set it whenever the data came
    from a STAC item, in fetch mode too: the output copies its datetime, platform, licence and
    other metadata from it.

    `datetime` defaults to the source item's acquisition time. `geometry` defaults to the
    footprint of the first raster asset, then to the source item's geometry.
    `extra_properties` are added to the item's properties last, so they win over computed ones.
    """

    id: str
    assets: Dict[str, Asset]
    source_item: Optional[Union[dict, StacItemInput]] = None
    datetime: Optional[dt.datetime] = None
    geometry: Optional[dict] = None
    extra_properties: dict = field(default_factory=dict)


@dataclass
class CollectionSpec:
    """
    The output collection. All items of a run go in one collection.

    `id` is the catalog ID, the same for every run. The collection ID is `<id>-<UTC time>-<random>`,
    unique per run. `renders` go on the collection and on every item; every render needs
    `assets` that each item has and an explicit `rescale`.
    `license` defaults to the first source item's licence, then to `other`.
    """

    id: str
    title: str
    description: str
    renders: Dict[str, dict] = field(default_factory=dict)
    keywords: Sequence[str] = ()
    license: Optional[str] = None
    extra_fields: dict = field(default_factory=dict)


@dataclass
class OutputSpec:
    """
    What `run()` returns.

    `customise(catalog)` is an escape hatch: it gets the built pystac Catalog before it is saved
    and validated, and can change anything. Use it only when the specs cannot express what you need.
    """

    collection: CollectionSpec
    items: List[ItemSpec]
    customise: Optional[Callable[[pystac.Catalog], None]] = None


def run_collection_id(base_id: str, now: dt.datetime) -> str:
    """Collection ID unique to this run, e.g. `ndvi-20261027T082302-3f9a1c`."""
    return f"{base_id}-{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


def _source_dict(source_item) -> dict:
    if isinstance(source_item, StacItemInput):
        return source_item.item
    return source_item or {}


def _is_inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _check_specs(output_dir: Path, collection: CollectionSpec, items: Sequence[ItemSpec]) -> None:
    """Refuse output that cannot be published or rendered, listing every problem at once."""
    problems = []
    if not items:
        problems.append("run() returned no items")

    item_ids = [item.id for item in items]
    for item_id in {i for i in item_ids if item_ids.count(i) > 1}:
        problems.append(f"Item ID {item_id!r} is used more than once")
    for item_id in item_ids:
        if not item_id or "/" in item_id or "\\" in item_id:
            problems.append(f"Item ID {item_id!r} is not usable as a file name")

    has_raster = False
    for item in items:
        if not item.assets:
            problems.append(f"Item {item.id!r} has no assets")
        for key, asset in item.assets.items():
            path = Path(asset.path)
            if not path.exists():
                problems.append(f"Asset {key!r} of item {item.id!r}: {path} does not exist")
                continue
            if not _is_inside(path, output_dir):
                problems.append(f"Asset {key!r} of item {item.id!r}: {path} is not under the output directory")
            if isinstance(asset, RasterAsset):
                has_raster = True
                errors = cog_problems(path)
                if errors:
                    problems.append(
                        f"Asset {key!r} of item {item.id!r}: {path.name} is not a valid COG ({'; '.join(errors)}). "
                        "Write it with eodh_workflow.write_cog or write_cog_chunked."
                    )

    if has_raster and not collection.renders:
        problems.append(
            "There are raster assets but CollectionSpec.renders is empty. Add a render for each raster, "
            "or use eodh_workflow.fallback_render(cog_path)."
        )
    for render_id, render in collection.renders.items():
        if not isinstance(render, dict):
            problems.append(f"Render {render_id!r} is not a dict")
            continue
        if not render.get("assets"):
            problems.append(f"Render {render_id!r} has no 'assets'")
        if not render.get("rescale"):
            problems.append(
                f"Render {render_id!r} has no 'rescale'. The tilers do not stretch the data by themselves, "
                "so a render without rescale shows a blank or saturated map."
            )
        for item in items:
            for key in render.get("assets") or []:
                if key not in item.assets:
                    problems.append(f"Render {render_id!r} uses asset {key!r}, which item {item.id!r} does not have")
                elif not isinstance(item.assets[key], RasterAsset):
                    problems.append(f"Render {render_id!r} uses asset {key!r}, which is not a RasterAsset")

    if problems:
        raise OutputError(problems)


def _nodata_value(nodata, dtype: str):
    if nodata is None:
        return None
    if math.isnan(nodata):
        return "nan"
    if math.isinf(nodata):
        return "inf" if nodata > 0 else "-inf"
    return int(nodata) if dtype.startswith(("int", "uint")) else float(nodata)


def _band_statistics(src) -> List[Optional[dict]]:
    try:
        stats = src.stats(approx=True)
    except Exception as e:  # e.g. a band with no valid pixels
        logger.warning(f"Could not compute band statistics: {e}")
        return [None] * src.count
    return [
        {"minimum": float(s.min), "maximum": float(s.max), "mean": float(s.mean), "stddev": float(s.std)} for s in stats
    ]


def _footprint(src) -> Tuple[dict, List[float]]:
    """
    Raster extent as an EPSG:4326 polygon and bbox, densified so curved edges are followed.
    rasterio >= 1.5 cuts geometries that cross the antimeridian.
    """
    left, bottom, right, top = src.bounds
    n = _DENSIFY_POINTS
    xs = [left + (right - left) * i / (n - 1) for i in range(n)]
    ys = [bottom + (top - bottom) * i / (n - 1) for i in range(n)]
    ring = (
        [(x, bottom) for x in xs]
        + [(right, y) for y in ys[1:]]
        + [(x, top) for x in reversed(xs[:-1])]
        + [(left, y) for y in reversed(ys[:-1])]
    )
    geometry = transform_geom(src.crs, "EPSG:4326", {"type": "Polygon", "coordinates": [ring]}, precision=7)
    bbox = transform_bounds(src.crs, "EPSG:4326", left, bottom, right, top, densify_pts=n)
    return geometry, [round(v, 7) for v in bbox]


def _geometry_bbox(geometry: dict) -> List[float]:
    """Bbox of a GeoJSON geometry, from its coordinates."""

    def points(coords):
        if coords and isinstance(coords[0], (int, float)):
            yield coords
        else:
            for c in coords:
                yield from points(c)

    if geometry.get("type") == "GeometryCollection":
        boxes = [_geometry_bbox(g) for g in geometry["geometries"]]
        return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    xs, ys = zip(*((p[0], p[1]) for p in points(geometry["coordinates"])))
    return [min(xs), min(ys), max(xs), max(ys)]


def _projection_fields(src) -> dict:
    fields = {
        "proj:shape": [src.height, src.width],
        "proj:transform": list(src.transform)[:6],
        "proj:bbox": list(src.bounds),
    }
    epsg = src.crs.to_epsg()
    if epsg:
        fields["proj:code"] = f"EPSG:{epsg}"
    else:
        fields["proj:wkt2"] = src.crs.to_wkt()
    if src.crs.is_projected:
        fields["gsd"] = abs(src.res[0])
    return fields


def _raster_bands(src, bands: Optional[List[dict]]) -> List[dict]:
    """`bands` for a raster asset, without statistics (those are not part of item_assets)."""
    if bands is not None and len(bands) != src.count:
        raise OutputError([f"{src.name} has {src.count} bands but RasterAsset.bands lists {len(bands)}"])
    result = []
    for index in range(src.count):
        band = dict(bands[index]) if bands else {"name": f"b{index + 1}"}
        if "common_name" in band:  # STAC 1.0 eo:bands spelling
            band["eo:common_name"] = band.pop("common_name")
        band["data_type"] = src.dtypes[index]
        nodata = _nodata_value(src.nodata, src.dtypes[index])
        if nodata is not None:
            band["nodata"] = nodata
        result.append(band)
    return result


@dataclass
class _RasterInfo:
    geometry: dict
    bbox: List[float]
    projection: dict
    bands: List[dict]
    statistics: List[Optional[dict]]


def _read_raster(asset: RasterAsset) -> _RasterInfo:
    # PAM off: computing statistics would otherwise leave a .aux.xml sidecar in the output.
    with rasterio.Env(GDAL_PAM_ENABLED="NO"), rasterio.open(asset.path) as src:
        geometry, bbox = _footprint(src)
        return _RasterInfo(
            geometry, bbox, _projection_fields(src), _raster_bands(src, asset.bands), _band_statistics(src)
        )


def _item_datetimes(spec: ItemSpec, source_properties: dict) -> Tuple[Optional[dt.datetime], dict]:
    """Acquisition datetime (or start/end range) of the item."""
    if spec.datetime:
        return spec.datetime, {}
    extra = {key: source_properties[key] for key in ("start_datetime", "end_datetime") if source_properties.get(key)}
    if source_properties.get("datetime"):
        return str_to_datetime(source_properties["datetime"]), extra
    if len(extra) == 2:
        return None, extra
    logger.warning(f"Item {spec.id!r} has no datetime and no source datetime; using the processing time")
    return dt.datetime.now(dt.timezone.utc), {}


def _extensions_for(properties: dict, assets: Iterable[dict]) -> List[str]:
    extensions = []
    if any(key.startswith("proj:") for key in properties) or any(
        key.startswith("proj:") for asset in assets for key in asset
    ):
        extensions.append(PROJECTION_EXTENSION)
    if properties.get("renders"):
        extensions.append(RENDER_EXTENSION)
    if any(key.startswith("eo:") for key in properties) or any(
        "eo:common_name" in band for asset in assets for band in asset.get("bands", [])
    ):
        extensions.append(EO_EXTENSION)
    return extensions


def _build_item(spec: ItemSpec, collection: CollectionSpec, now: str) -> pystac.Item:
    source = _source_dict(spec.source_item)
    source_properties = source.get("properties", {})

    rasters = {key: _read_raster(a) for key, a in spec.assets.items() if isinstance(a, RasterAsset)}
    first = next(iter(rasters.values()), None)

    geometry = spec.geometry or (first.geometry if first else None) or source.get("geometry")
    if not geometry:
        raise OutputError([f"Item {spec.id!r} has no raster asset and no geometry; set ItemSpec.geometry"])
    bbox = first.bbox if (first and not spec.geometry) else [round(v, 7) for v in _geometry_bbox(geometry)]

    item_datetime, datetime_range = _item_datetimes(spec, source_properties)
    properties = {
        **datetime_range,
        "created": now,
        "updated": now,
        **{key: source_properties[key] for key in COPIED_SOURCE_PROPERTIES if key in source_properties},
        # Projection of the first raster on the item; other rasters on a different grid carry their own.
        **(first.projection if first else {}),
        "eodh:product": collection.id,
    }
    if source.get("id"):
        properties["eodh:source_item_id"] = source["id"]
    if collection.renders:
        properties["renders"] = copy.deepcopy(collection.renders)
    properties.update(spec.extra_properties)

    asset_dicts = {}
    for key, asset in spec.assets.items():
        fields = {}
        if isinstance(asset, RasterAsset):
            info = rasters[key]
            if info.projection != first.projection:
                fields.update(info.projection)
            fields["bands"] = [
                {**band, "statistics": stats} if stats else band for band, stats in zip(info.bands, info.statistics)
            ]
        fields.update(asset.extra_fields)
        asset_dicts[key] = fields

    item = pystac.Item(
        id=spec.id,
        geometry=geometry,
        bbox=bbox,
        datetime=item_datetime,
        properties=properties,
        stac_extensions=_extensions_for(properties, asset_dicts.values()),
    )
    for key, asset in spec.assets.items():
        item.add_asset(
            key,
            pystac.Asset(
                href=str(Path(asset.path).resolve()),
                media_type=pystac.MediaType.COG if isinstance(asset, RasterAsset) else asset.media_type,
                roles=list(asset.roles),
                title=asset.title or (f"{collection.title} (COG)" if isinstance(asset, RasterAsset) else None),
                description=asset.description,
                extra_fields=asset_dicts[key],
            ),
        )
    return item


def _item_assets(item: pystac.Item) -> Dict[str, pystac.ItemAssetDefinition]:
    """Collection `item_assets` from an item's assets, without per-item values."""
    definitions = {}
    for key, asset in item.assets.items():
        extra = {}
        if "bands" in asset.extra_fields:
            extra["bands"] = [
                {k: v for k, v in band.items() if k != "statistics"} for band in asset.extra_fields["bands"]
            ]
        definitions[key] = pystac.ItemAssetDefinition.create(
            title=asset.title,
            description=asset.description,
            media_type=asset.media_type,
            roles=asset.roles,
            extra_fields=extra or None,
        )
    return definitions


def write_outputs(
    output_dir: Path,
    collection: CollectionSpec,
    items: Sequence[ItemSpec],
    customise: Optional[Callable[[pystac.Catalog], None]] = None,
) -> Path:
    """Write the output STAC for `items` to `output_dir`, validate it, and return the catalog path."""
    output_dir = Path(output_dir).resolve()
    _check_specs(output_dir, collection, items)

    run_time = dt.datetime.now(dt.timezone.utc)
    now = pystac.utils.datetime_to_str(run_time)
    stac_items = [_build_item(spec, collection, now) for spec in items]

    source_licence = next(
        (
            _source_dict(spec.source_item).get("properties", {}).get("license")
            for spec in items
            if _source_dict(spec.source_item).get("properties", {}).get("license")
        ),
        None,
    )
    collection_id = run_collection_id(collection.id, run_time)
    stac_collection = pystac.Collection(
        id=collection_id,
        title=f"{collection.title} – {run_time:%Y-%m-%d %H:%M} UTC",
        description=collection.description,
        extent=pystac.Extent(pystac.SpatialExtent([stac_items[0].bbox]), pystac.TemporalExtent([[None, None]])),
        # No licence link: stage-out would re-host it.
        license=collection.license or source_licence or "other",
        keywords=list(collection.keywords),
        providers=[
            pystac.Provider(
                name="EO DataHub",
                roles=[pystac.ProviderRole.PROCESSOR, pystac.ProviderRole.HOST],
                url="https://eodatahub.org.uk",
            )
        ],
        stac_extensions=[
            e
            for e in _extensions_for(
                {"renders": collection.renders}, [a.to_dict() for a in stac_items[0].assets.values()]
            )
            if e != PROJECTION_EXTENSION
        ],
        extra_fields={"renders": copy.deepcopy(collection.renders), **collection.extra_fields}
        if collection.renders
        else dict(collection.extra_fields),
    )
    stac_collection.item_assets = _item_assets(stac_items[0])

    catalog = pystac.Catalog(
        id=collection.id,
        title=f"{collection.title} outputs",
        description=f"Outputs of the EODH {collection.title} workflow, one collection per run.",
    )
    catalog.add_child(stac_collection)
    for item in stac_items:
        stac_collection.add_item(item)
    # ADES stage-out does not recompute the extent of collections it is given.
    stac_collection.update_extent_from_items()

    catalog.normalize_hrefs(str(output_dir))
    for item in stac_items:
        item.make_asset_hrefs_relative()
    if customise:
        customise(catalog)
    catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)

    assert_valid_output_dir(output_dir)
    catalog_path = output_dir / "catalog.json"
    logger.info(f"Wrote STAC catalog {catalog_path} (collection {collection_id!r}, {len(stac_items)} items)")
    return catalog_path
