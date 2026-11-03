"""Choose the explicit worker family without inventing distribution/runner mappings."""

import os

from contract import assignment, require
from native import build


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--assignment", required=True)
    parser.add_argument("--assignment-sha256", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    selected = assignment(arguments.assignment, arguments.assignment_sha256)
    require(
        selected["execution"] == os.environ["EXECUTION"] and selected["attempt"] == os.environ["ATTEMPT"],
        "workflow inputs do not match assignment",
    )
    build(arguments)


if __name__ == "__main__":
    main()
