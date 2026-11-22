"""CollisionGuard command line. Experimental merge-risk triage for two tasks."""

import argparse
import json
import sys
from pathlib import Path

from .features import pair_features
from .files import (language_from_files, list_repo_files, predict_files,
                    shared_directories, shared_files)
from .model import contributions, load_artifact, score

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = ROOT / "models" / "collisionguard-v0.1.joblib"


def _read_task(value, path):
    if value is not None:
        return value
    if path is not None:
        return Path(path).read_text(encoding="utf-8")
    raise SystemExit("provide --task-a or --task-a-file (and the same for B)")


def build_report(repo, task_a, task_b, agent_a=None, agent_b=None,
                 model_path=DEFAULT_MODEL, top_k=5):
    artifact = load_artifact(model_path)
    paths = list_repo_files(repo)
    if not paths:
        raise SystemExit(f"no tracked files found in {repo}")
    same_agent = bool(agent_a and agent_b and agent_a == agent_b)
    features = pair_features(task_a, task_b,
                             language=language_from_files(paths),
                             tree_files=len(paths),
                             same_agent=same_agent,
                             agent_a=agent_a,
                             agent_b=agent_b)
    result = score(artifact, features)
    ranked_a = predict_files(task_a, paths, top_k=top_k)
    ranked_b = predict_files(task_b, paths, top_k=top_k)
    files_a = [path for path, _ in ranked_a]
    files_b = [path for path, _ in ranked_b]
    shared = shared_files(files_a, files_b)
    bands = artifact["metadata"].get("bands", {})
    report = {
        "repo": str(Path(repo).resolve()),
        "tasks": {"a": task_a, "b": task_b},
        "agents": {"a": agent_a, "b": agent_b},
        "risk": result,
        "band_reference": bands.get(result["band"]),
        "likely_files": {
            "a": [{"path": path, "score": score_value} for path, score_value in ranked_a],
            "b": [{"path": path, "score": score_value} for path, score_value in ranked_b],
            "shared": shared,
            "shared_directories": shared_directories(files_a, files_b),
        },
        "reasons": contributions(artifact, features),
        "model": {
            "version": artifact["metadata"].get("version"),
            "trained_on": artifact["metadata"].get("trained_on"),
            "metrics": artifact["metrics"],
        },
        "caveat": ("Experimental triage on a retrospective cohort. It ranks risk "
                   "above chance but is not a safety guarantee. Use it to order "
                   "review or serialize suspicious pairs, not to approve work."),
    }
    if not agent_a or not agent_b:
        report["warning"] = ("agent names missing: the model treats them as unknown, "
                             "so the historical band rates may not apply")
    return report


def _print(report):
    risk = report["risk"]
    print(f"Risk band: {risk['band']}  (raw {risk['raw_score']:.3f}, "
          f"calibrated {risk['calibrated_probability']:.3f}, "
          f"percentile {risk['percentile'] * 100:.0f})")
    reference = report.get("band_reference")
    if reference:
        print(f"Historical conflict rate for this band: {reference['rate']:.1%} "
              f"({reference['conflicts']}/{reference['pairs']} pairs)")
    print()
    print("Likely files for A:")
    for row in report["likely_files"]["a"]:
        print(f"  {row['path']}  ({row['score']:.3f})")
    print("Likely files for B:")
    for row in report["likely_files"]["b"]:
        print(f"  {row['path']}  ({row['score']:.3f})")
    if report["likely_files"]["shared"]:
        print("Shared predicted files:")
        for path in report["likely_files"]["shared"]:
            print(f"  {path}")
    if report["reasons"]:
        print("Top factors:")
        for item in report["reasons"]:
            print(f"  {item['reason']} ({item['direction']} risk, {item['weight']:+.2f})")
    print()
    if report.get("warning"):
        print("Warning: " + report["warning"])
    print(report["caveat"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="path to a Git repository")
    parser.add_argument("--task-a")
    parser.add_argument("--task-a-file")
    parser.add_argument("--task-b")
    parser.add_argument("--task-b-file")
    parser.add_argument("--agent-a")
    parser.add_argument("--agent-b")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    task_a = _read_task(args.task_a, args.task_a_file)
    task_b = _read_task(args.task_b, args.task_b_file)
    report = build_report(args.repo, task_a, task_b, args.agent_a, args.agent_b,
                          args.model, args.top_k)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
