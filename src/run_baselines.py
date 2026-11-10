"""Run repository-held-out baseline demonstrations on the public data."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from baselines import TfidfBaseline, LogisticRegressionBaseline

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "data" / "parallact-12" / "features.json"
TARGETS = ROOT / "data" / "parallact-12" / "targets.json"

# Synthetic data 

SYNTHETIC_FEATURES = [
    {
        "instance_id": "synth-001",
        "repo": "example/webapp",
        "base_commit": "abc123",
        "task_a": "Fix the login form validation error when users enter special characters in the password field. Update the authentication handler to properly escape input.",
        "task_b": "Refactor the login page CSS to match the new design system. Update button styles and form layout to use the shared component library.",
    },
    {
        "instance_id": "synth-002",
        "repo": "example/webapp",
        "base_commit": "abc123",
        "task_a": "Add rate limiting to the API endpoint /api/v1/users to prevent abuse. Implement a sliding window counter using Redis.",
        "task_b": "Update the API endpoint /api/v1/users to support pagination. Add query parameters for page and page_size with proper validation.",
    },
    {
        "instance_id": "synth-003",
        "repo": "example/cli-tool",
        "base_commit": "def456",
        "task_a": "Add a --verbose flag to the build command that prints detailed compilation output including file paths and timings.",
        "task_b": "Implement a new 'deploy' subcommand that packages the build artifacts and uploads them to the configured remote server.",
    },
    {
        "instance_id": "synth-004",
        "repo": "example/cli-tool",
        "base_commit": "def456",
        "task_a": "Fix the configuration file parser to handle nested YAML keys with dots in their names. Update the config module and its tests.",
        "task_b": "Fix the configuration file parser to support environment variable interpolation in YAML values. Add a preprocessor to the config module.",
    },
    {
        "instance_id": "synth-005",
        "repo": "example/data-pipeline",
        "base_commit": "ghi789",
        "task_a": "Optimize the ETL batch processor to use connection pooling for database writes. Update the database adapter and connection manager.",
        "task_b": "Add CSV export functionality to the ETL pipeline output stage. Implement a new CSVWriter class in the output module.",
    },
    {
        "instance_id": "synth-006",
        "repo": "example/data-pipeline",
        "base_commit": "ghi789",
        "task_a": "Refactor the data validation module to use a schema-based approach. Replace inline checks with JSON schema validation in the ingestion step.",
        "task_b": "Add data validation rules for the new 'address' field type in the ingestion pipeline. Update the validation module and schema definitions.",
    },
    {
        "instance_id": "synth-007",
        "repo": "example/frontend",
        "base_commit": "jkl012",
        "task_a": "Implement dark mode support across all dashboard components. Add a theme toggle to the settings panel and update the global stylesheet.",
        "task_b": "Redesign the dashboard layout to be responsive on mobile devices. Update the grid system and component layouts in the global stylesheet.",
    },
    {
        "instance_id": "synth-008",
        "repo": "example/frontend",
        "base_commit": "jkl012",
        "task_a": "Add unit tests for the user profile component. Test the form validation, avatar upload, and preference saving flows.",
        "task_b": "Implement the notification preferences panel in the user settings page. Add toggle switches for email, push, and in-app notifications.",
    },
]

# Synthetic labels: pairs 2, 4, 6, 7 conflict (tasks touch same files/modules)
SYNTHETIC_TARGETS = [
    {"instance_id": "synth-001", "status": "complete", "label": "clean"},
    {"instance_id": "synth-002", "status": "complete", "label": "conflict"},
    {"instance_id": "synth-003", "status": "complete", "label": "clean"},
    {"instance_id": "synth-004", "status": "complete", "label": "conflict"},
    {"instance_id": "synth-005", "status": "complete", "label": "clean"},
    {"instance_id": "synth-006", "status": "complete", "label": "conflict"},
    {"instance_id": "synth-007", "status": "complete", "label": "conflict"},
    {"instance_id": "synth-008", "status": "complete", "label": "clean"},
]


def load_data(synthetic=False):
    """Load the public bundle, or the explicitly requested smoke examples."""
    if synthetic:
        return SYNTHETIC_FEATURES, SYNTHETIC_TARGETS, "synthetic (built-in examples)"
    return (json.loads(FEATURES.read_text(encoding="utf-8")),
            json.loads(TARGETS.read_text(encoding="utf-8")),
            "public ParallACT-12")


def join_data(features, targets):
    """Validate and join two complete lists by their exact instance IDs."""
    def index(records, name):
        if not isinstance(records, list) or not records:
            raise ValueError(f"{name} must be a nonempty list")
        result = {}
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"{name} records must be objects")
            iid = record.get("instance_id")
            if not isinstance(iid, str) or not iid.strip():
                raise ValueError(f"{name} records require nonempty string IDs")
            if iid in result:
                raise ValueError(f"duplicate {name} ID: {iid}")
            result[iid] = record
        return result

    feature_map = index(features, "feature")
    target_map = index(targets, "target")
    if feature_map.keys() != target_map.keys():
        raise ValueError("feature and target IDs must match exactly")
    pairs, labels, repos, ids = [], [], [], []
    for iid, feature in feature_map.items():
        for field in ("task_a", "task_b", "repo"):
            value = feature.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{iid}: {field} must be a nonempty string")
        repo = feature["repo"]
        if len(repo.split("/")) != 2 or any(not part or any(ch.isspace() for ch in part) for part in repo.split("/")):
            raise ValueError(f"{iid}: repo must have the form owner/name")
        target = target_map[iid]
        if target.get("status") != "complete" or target.get("label") not in ("clean", "conflict"):
            raise ValueError(f"{iid}: target must be complete with a clean or conflict label")
        pairs.append((feature["task_a"], feature["task_b"]))
        labels.append(int(target["label"] == "conflict"))
        repos.append((feature["repo"], feature["repo"]))
        ids.append(iid)
    return pairs, labels, repos, ids


def _folds(repos):
    # Repository identifiers are case-insensitive on the source hosting service.
    groups = [repo[0].casefold() for repo in repos]
    for group in dict.fromkeys(groups):
        yield ([i for i, value in enumerate(groups) if value != group],
               [i for i, value in enumerate(groups) if value == group])


def _report(name, scores, labels, ids):
    print(f"\n{name} (leave-one-repository-out)")
    for iid, score, label in zip(ids, scores, labels):
        rendered = "unavailable" if score is None else f"{score:.3f}"
        print(f"{iid}: {rendered} ({'conflict' if label else 'clean'})")
    print(f"Coverage: {sum(score is not None for score in scores)}/{len(scores)} pairs")


def run_tfidf_baseline(pairs, labels, repos, ids):
    scores = [None] * len(pairs)
    for train, test in _folds(repos):
        if not train:
            continue
        model = TfidfBaseline().fit([text for i in train for text in pairs[i]])
        for i in test:
            scores[i] = model.predict_score(*pairs[i])
    _report("TF-IDF", scores, labels, ids)
    return scores


def run_logistic_baseline(pairs, labels, repos, ids):
    scores = [None] * len(pairs)
    for train, test in _folds(repos):
        if len({labels[i] for i in train}) < 2:
            continue
        model = LogisticRegressionBaseline().fit(
            [pairs[i] for i in train], [labels[i] for i in train],
            [repos[i] for i in train])
        for i in test:
            scores[i] = model.predict_proba(*pairs[i], *repos[i])
    _report("Logistic regression", scores, labels, ids)
    return scores


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true", help="use built-in smoke examples")
    args = parser.parse_args(argv)
    features, targets, source = load_data(args.synthetic)
    pairs, labels, repos, ids = join_data(features, targets)
    print(f"Data source: {source}; {len(pairs)} pairs")
    print("Demo only: this small dataset does not establish prediction accuracy.")
    run_tfidf_baseline(pairs, labels, repos, ids)
    run_logistic_baseline(pairs, labels, repos, ids)


if __name__ == "__main__":
    main()
