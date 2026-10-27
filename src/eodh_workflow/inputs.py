"""
Workflow inputs: the STAC item that ADES stage-in wrote to disk, and the string parameters from the CWL.

Stage-in writes a directory like this and passes it to the tool as a CWL `Directory`:

    catalog.json                  with one `item` link
    <item_id>/<item_id>.json      the item, with asset hrefs relative to it
    <item_id>/<asset files>

Stage-in drops the item's links, so the tool cannot see the source item's URL or its collection.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

logger = logging.getLogger(__name__)

GEOTIFF_MEDIA_TYPES = ("image/tiff", "image/vnd.stac.geotiff")


class Band(NamedTuple):
    """One raster band on disk: file path and 1-based band index."""

    path: Path
    index: int


def asset_bands(asset: dict) -> List[dict]:
    """Band list of an asset: STAC 1.0 `eo:bands` or STAC 1.1 `bands`."""
    return asset.get("bands") or asset.get("eo:bands") or []


def band_common_name(band: dict) -> Optional[str]:
    return band.get("eo:common_name") or band.get("common_name")


def is_geotiff(asset: dict) -> bool:
    media_type = asset.get("type") or ""
    href = asset.get("href") or ""
    return media_type.startswith(GEOTIFF_MEDIA_TYPES) or href.lower().endswith((".tif", ".tiff"))


@dataclass(frozen=True)
class StacItemInput:
    """The staged STAC item. `item` is the item JSON as a dict."""

    item: dict
    item_path: Path

    @property
    def id(self) -> str:
        return self.item["id"]

    @property
    def properties(self) -> dict:
        return self.item.get("properties", {})

    @property
    def assets(self) -> Dict[str, dict]:
        return self.item.get("assets", {})

    def asset_path(self, key: str) -> Path:
        """Local path of asset `key`. Raises KeyError if the item has no such asset, and
        FileNotFoundError if stage-in did not download it."""
        if key not in self.assets:
            raise KeyError(f"Item {self.id!r} has no asset {key!r}. Assets: {sorted(self.assets)}")
        href = self.assets[key].get("href")
        if not href:
            raise ValueError(f"Asset {key!r} of item {self.id!r} has no href")
        path = (self.item_path.parent / href).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Asset {key!r} of item {self.id!r} is not on disk at {path}")
        return path

    def band(self, common_name: str) -> Band:
        """
        Find the band with STAC common name `common_name` (`red`, `nir`, ...).

        Single-band GeoTIFF assets are tried first (for example Element84 Sentinel-2 `red`), then
        multi-band assets (for example a CEDA ARD `cog`), then an asset whose key is `common_name`.
        """
        candidates = []
        for key, asset in self.assets.items():
            if not is_geotiff(asset):
                continue
            bands = asset_bands(asset)
            for index, band in enumerate(bands, start=1):
                if band_common_name(band) == common_name:
                    candidates.append((len(bands), key, index))
        if candidates:
            _, key, index = min(candidates, key=lambda c: c[0])
            return Band(self.asset_path(key), index)
        if common_name in self.assets and is_geotiff(self.assets[common_name]):
            return Band(self.asset_path(common_name), 1)

        found = sorted(
            {name for asset in self.assets.values() for name in map(band_common_name, asset_bands(asset)) if name}
        )
        raise KeyError(f"Item {self.id!r} has no band with common name {common_name!r}. Common names: {found}")


@dataclass(frozen=True)
class WorkflowInputs:
    """
    What `run()` receives.

    `stac_item` is the staged item, or None when the workflow has no stage-in input (fetch mode).
    `params` holds every other CWL input as a string, keyed by its command-line name. Optional
    inputs that the job left out are not in `params`.
    """

    stac_item: Optional[StacItemInput] = None
    params: Dict[str, str] = field(default_factory=dict)


def read_staged_item(stac_item_dir: Path) -> StacItemInput:
    """Read the item that ADES stage-in wrote to `stac_item_dir`."""
    stac_item_dir = Path(stac_item_dir)
    catalog_path = stac_item_dir / "catalog.json"
    if not catalog_path.exists():
        raise FileNotFoundError(f"No catalog.json in staged directory {stac_item_dir}")

    catalog = json.loads(catalog_path.read_text())
    item_links = [link for link in catalog.get("links", []) if link.get("rel") == "item"]
    if not item_links:
        raise ValueError(f"No item link in {catalog_path}")
    if len(item_links) > 1:
        # One Directory input is one item. Several items need Directory[] stage-in, which the starter does not support.
        raise ValueError(f"{catalog_path} links {len(item_links)} items; this workflow takes one")

    item_path = (stac_item_dir / item_links[0]["href"]).resolve()
    if not item_path.exists():
        raise FileNotFoundError(f"Staged item {item_path} does not exist")
    item = json.loads(item_path.read_text())
    logger.info(f"Staged item {item['id']!r} at {item_path}, assets {sorted(item.get('assets', {}))}")
    return StacItemInput(item=item, item_path=item_path)
