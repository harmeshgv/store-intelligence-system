import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from experiments.bench_configs import DEFAULT_EXPERIMENTS
from experiments.bench_runner import run_experiment


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main():
    parser = argparse.ArgumentParser(
        description="Run all experiment configs and write final JSON summary."
    )
    parser.add_argument(
        "--videos",
        nargs="+",
        default=["data/CAM 3.mp4"],
        help="Video paths to evaluate (space separated).",
    )
    parser.add_argument(
        "--frame-limit",
        type=int,
        default=900,
        help="Max frames per run (0 = full video).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="experiments/final_experiment_data.json",
        help="Output JSON path.",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_results = []
    print("\n[Experiments] Starting benchmark runs...\n")
    for video in args.videos:
        for cfg in DEFAULT_EXPERIMENTS:
            print(f"[RUN] video={video} config={cfg.name}")
            result = run_experiment(cfg, video, frame_limit=args.frame_limit)
            all_results.append(result)
            if result.get("ok"):
                print(
                    f"      unique={result['unique_humans_estimate']} "
                    f"fps={result['avg_fps']} det={result['detections_total']}"
                )
            else:
                if result.get("skipped"):
                    print(f"      skipped: {result.get('error')}")
                else:
                    print(f"      failed: {result.get('error')}")

    summary = {
        "generated_at": _now_iso(),
        "frame_limit": args.frame_limit,
        "videos": args.videos,
        "experiments_count": len(DEFAULT_EXPERIMENTS),
        "results": all_results,
    }

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n[Experiments] Done. Final JSON written to: {output_path}")


if __name__ == "__main__":
    main()

