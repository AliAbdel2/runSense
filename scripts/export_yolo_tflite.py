#!/usr/bin/env python3
"""Export a YOLO11 detector to TFLite for on-device perception.

This is a **one-time, offline tooling step**, not part of the application, the
build, or the test suite. Nothing in ``runsense/`` imports it and CI never runs
it: it downloads model weights, pulls in TensorFlow via ``ultralytics``, and
takes minutes to tens of minutes depending on the machine.

Run it on a workstation with the optional perception extra installed::

    pip install '.[perception]'
    python scripts/export_yolo_tflite.py --model yolo11n.pt --imgsz 640 --int8

The resulting ``.tflite`` file is what the mobile app's on-device inference
would load (see ``mobile/src/hooks/usePerceptionStream.ts``, which is currently
an unimplemented placeholder — no model is bundled or loaded today).

Honesty notes, matching the rest of this repo's documentation:

* The exported model has not been run, benchmarked, or accuracy-checked here.
  No device, camera, or labelled footage exists in this environment.
* ``--int8`` quantisation changes detection accuracy. Ultralytics calibrates it
  against a dataset (COCO128 by default, or ``--data``); the result must be
  re-measured against real footage before anyone relies on it for obstacle
  alerts. Nothing in this repo has done that measurement.
* Per-frame latency on a phone is unknown. The triage budgets in
  ``runsense/triage.py`` assume a frame pipeline that does not exist yet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a YOLO11 model to TFLite for on-device inference (offline tooling).",
    )
    parser.add_argument(
        "--model",
        default="yolo11n.pt",
        help="Model name or path passed to ultralytics.YOLO. Downloaded on first use. Default: yolo11n.pt",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="Square inference size baked into the exported graph. Default: 640",
    )
    parser.add_argument(
        "--int8",
        action="store_true",
        help="Emit an int8-quantised model. Smaller and faster, with accuracy that must be re-measured.",
    )
    parser.add_argument(
        "--data",
        default=None,
        help="Ultralytics dataset YAML used to calibrate int8 quantisation. Ignored without --int8.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional destination to copy the exported file to. Default: leave it where ultralytics wrote it.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        # Imported lazily and inside main() so that merely importing this module
        # (or listing scripts/) never pulls in torch/TensorFlow.
        from ultralytics import YOLO
    except ImportError:
        print(
            "ultralytics is not installed. This script is offline tooling; install the optional\n"
            "perception extra first:\n\n    pip install '.[perception]'\n",
            file=sys.stderr,
        )
        return 2

    export_kwargs: dict[str, object] = {"format": "tflite", "imgsz": args.imgsz}
    if args.int8:
        export_kwargs["int8"] = True
        if args.data:
            export_kwargs["data"] = args.data

    model = YOLO(args.model)
    exported = model.export(**export_kwargs)
    exported_path = Path(str(exported))
    print(f"Exported: {exported_path}")

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(exported_path.read_bytes())
        print(f"Copied to: {args.out}")

    print(
        "Reminder: accuracy and phone latency of this export are unmeasured. "
        "Do not treat it as a validated obstacle detector."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
