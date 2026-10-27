"""
Command-line helpers, used by the Makefile:

    python -m eodh_workflow stage <item.json> <staged_dir>   write a synthetic stage-in directory for an item
    python -m eodh_workflow validate <output_dir>            check a workflow output directory
    python -m eodh_workflow checksum [--write]               print (or record) the checksum of the helpers
"""

import json
import logging
import sys
from pathlib import Path

from . import checksum
from .testing import stage_item
from .validate import output_problems

USAGE = __doc__.strip()


def main(argv) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(argv) == 3 and argv[0] == "stage":
        stage_item(json.loads(Path(argv[1]).read_text()), Path(argv[2]))
        return 0
    if len(argv) == 2 and argv[0] == "validate":
        problems = output_problems(Path(argv[1]))
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        print(f"{len(problems)} problem(s) in {argv[1]}" if problems else f"{argv[1]} is valid", file=sys.stderr)
        return 1 if problems else 0
    if argv[:1] == ["checksum"] and argv[1:] in ([], ["--write"]):
        value = checksum.compute()
        if argv[1:] == ["--write"]:
            checksum.CHECKSUM_FILE.write_text(value + "\n")
        print(value)
        return 0
    print(USAGE, file=sys.stderr)
    return 2


sys.exit(main(sys.argv[1:]))
