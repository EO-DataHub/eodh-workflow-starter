"""
Entrypoint the CWL calls. Do not edit: put your code in workflow.py.

    python main.py [--stac_item_dir=<staged dir>] [--output_dir=<dir>] [--<param>=<value> ...]

`--stac_item_dir` is the directory ADES stage-in wrote. Leave it out when the workflow fetches
its own data. Every other `--name=value` argument goes to `run()` as `inputs.params["name"]`.
"""

import gc
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import workflow
from eodh_workflow import WorkflowInputs, log_memory_usage, read_staged_item, write_outputs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger("main")


def parse_args(argv: List[str]) -> Tuple[Path, Optional[Path], Dict[str, str]]:
    """Split `--name=value` and `--name value` arguments into output dir, stage-in dir and params."""
    args: Dict[str, str] = {}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if not arg.startswith("--") or arg == "--":
            raise SystemExit(f"Unexpected argument {arg!r}; arguments must be --name=value")
        if "=" in arg:
            name, value = arg[2:].split("=", 1)
        elif index + 1 < len(argv) and not argv[index + 1].startswith("--"):
            name, value = arg[2:], argv[index + 1]
            index += 1
        else:
            raise SystemExit(f"Argument {arg!r} has no value")
        args[name] = value
        index += 1

    output_dir = Path(args.pop("output_dir", "."))
    stac_item_dir = args.pop("stac_item_dir", None)
    return output_dir, Path(stac_item_dir) if stac_item_dir else None, args


def main(argv: Optional[List[str]] = None) -> Path:
    output_dir, stac_item_dir, params = parse_args(sys.argv[1:] if argv is None else argv)
    log_memory_usage("at start")
    inputs = WorkflowInputs(
        stac_item=read_staged_item(stac_item_dir) if stac_item_dir else None,
        params=params,
    )
    logger.info(f"Params: {params}")

    output_dir.mkdir(parents=True, exist_ok=True)
    spec = workflow.run(inputs, output_dir.resolve())
    gc.collect()
    log_memory_usage("before writing STAC")
    catalog_path = write_outputs(output_dir, spec.collection, spec.items, spec.customise)
    log_memory_usage("at end")
    return catalog_path


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Workflow failed")
        sys.exit(1)
