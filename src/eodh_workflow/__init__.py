"""
EODH workflow helpers. Workflow authors do not edit this folder: to upgrade, replace it with the
folder from a newer eodh-workflow-starter tag. See AGENTS.md.
"""

from .cog import write_cog
from .inputs import Band, StacItemInput, WorkflowInputs, read_staged_item
from .memory import available_memory_mb, log_memory_usage
from .outputs import CollectionSpec, FileAsset, ItemSpec, OutputSpec, RasterAsset, write_outputs
from .raster import write_cog_chunked
from .renders import fallback_render, remap_source_renders
from .validate import OutputError, output_problems

__version__ = "0.1.0"

__all__ = [
    "Band",
    "CollectionSpec",
    "FileAsset",
    "ItemSpec",
    "OutputError",
    "OutputSpec",
    "RasterAsset",
    "StacItemInput",
    "WorkflowInputs",
    "available_memory_mb",
    "fallback_render",
    "log_memory_usage",
    "output_problems",
    "read_staged_item",
    "remap_source_renders",
    "write_cog",
    "write_cog_chunked",
    "write_outputs",
]
