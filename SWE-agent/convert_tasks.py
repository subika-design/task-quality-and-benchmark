"""Convert task JSONL files to SWE-agent format."""

import argparse
import json
from pathlib import Path


def convert_tasks(src: Path, out: Path, *, arch: str = "x86_64") -> None:
    with src.open() as f, out.open("w") as w:
        for line in f:
            row = json.loads(line)
            iid = row["instance_id"]
            # Harness builds sweb.eval.{arch}.{instance_id.lower()}:latest
            image_key = iid.lower()
            w.write(
                json.dumps(
                    {
                        "instance_id": iid,
                        "problem_statement": row["problem_statement"],
                        "image_name": f"sweb.eval.{arch}.{image_key}:latest",
                        "repo_name": "testbed",
                        "base_commit": row["base_commit"],
                    }
                )
                + "\n"
            )


def get_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to the input JSONL file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Path to the output JSONL file (default: <input_stem>_sweagent<suffix>)",
    )
    parser.add_argument(
        "--arch",
        default="x86_64",
        help="Docker image arch tag (must match SWE-bench prepare_images --arch)",
    )
    return parser


def main() -> None:
    args = get_cli_parser().parse_args()
    out = args.output or args.input.with_name(f"{args.input.stem}_sweagent{args.input.suffix}")
    convert_tasks(args.input, out, arch=args.arch)


if __name__ == "__main__":
    main()
