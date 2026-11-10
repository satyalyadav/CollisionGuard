"""Export or verify the curated task bundle without publishing run outputs."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/parallact-12"
FEATURE_KEYS = {"instance_id", "repo", "base_commit", "task_a", "task_b"}
TARGET_KEYS = {"instance_id", "status", "label"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(body):
    return hashlib.sha256(body).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check_records(features, targets, cases):
    feature_ids = [record["instance_id"] for record in features]
    target_ids = [record["instance_id"] for record in targets]
    if len(feature_ids) != 12 or len(set(feature_ids)) != 12:
        raise ValueError("Expected twelve unique task pairs")
    if len(target_ids) != 12 or set(feature_ids) != set(target_ids):
        raise ValueError("Features and targets must have identical unique IDs")
    by_id = {Path(case["path"]).stem: case for case in cases}
    labels = {record["instance_id"]: record for record in targets}
    if set(by_id) != set(feature_ids):
        raise ValueError("Release IDs differ from the verified recovery")
    for feature in features:
        if set(feature) != FEATURE_KEYS:
            raise ValueError("Unexpected predictor field")
        case = by_id[feature["instance_id"]]
        target = labels[feature["instance_id"]]
        if set(target) != TARGET_KEYS or target["status"] != "complete":
            raise ValueError("Unexpected or incomplete target")
        if feature["repo"] != case["repo"] or feature["base_commit"] != case["base"]:
            raise ValueError("Repository or base differs from recovery")
        hashes = [digest(feature[key].encode("utf-8")) for key in ("task_a", "task_b")]
        if hashes != case["task_sha256"]:
            raise ValueError("Task text differs from normalized verified wording")
        replay = case["replay"]
        if (case["association"] != "valid" or replay["status"] != "complete"
                or not replay["repeat_identical"]
                or replay["snapshot_tree"] != replay["expected_tree"]
                or target["label"] != replay["label"]):
            raise ValueError("Label lacks the recorded verification")
    if sorted(record["label"] for record in targets) != ["clean"] * 7 + ["conflict"] * 5:
        raise ValueError("Unexpected label counts")
    if len({record["repo"] for record in features}) != 8:
        raise ValueError("Unexpected repository count")


def export(output, private):
    features = read_json(private / "features.json")
    targets = read_json(private / "targets.json")
    cases = read_json(ROOT / "data/parallact-recovery/cases.json")["cases"]
    notices = read_json(output / "licenses/sources.json")["upstream_notices"]
    for feature in features:
        for key in ("task_a", "task_b"):
            feature[key] = feature[key].strip()
    check_records(features, targets, cases)
    provenance = []
    for case in cases:
        notice = next(item for item in notices if item["repo"] == case["repo"]
                      and item["base_commit"] == case["base"])
        provenance.append({
            "instance_id": Path(case["path"]).stem,
            "website_source": case["run_url"],
            "website_run_sha256": case["run_sha256"],
            "matching_seed_source": case["seed_url"],
            "matching_seed_sha256": case["seed_sha256"],
            "task_sha256": case["task_sha256"],
            "upstream_base": f"https://github.com/{case['repo']}/tree/{case['base']}",
            "task_a_terms": {"presentation": "CC-BY-SA-4.0",
                             "upstream_declaration": notice["declared_license"],
                             "notice_file": "licenses/" + notice["file"]},
            "task_b_terms": {"presentation": "CC-BY-SA-4.0"},
            "site_revision": case["site_revision"],
            "execution_revision": case["execution_revision"],
        })
    dump(output / "features.json", features)
    dump(output / "targets.json", targets)
    dump(output / "provenance.json", provenance)
    files = sorted(path for path in output.rglob("*") if path.is_file()
                   and path.name != "SHA256SUMS")
    (output / "SHA256SUMS").write_text("".join(
        f"{digest(path.read_bytes())}  {path.relative_to(output).as_posix()}\n"
        for path in files), encoding="utf-8")


def verify(output):
    expected_files = set()
    for line in (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = output / relative
        if not path.resolve().is_relative_to(output.resolve()) or relative in expected_files:
            raise ValueError("Invalid checksum path")
        expected_files.add(relative)
        if digest(path.read_bytes()) != expected:
            raise ValueError(f"Checksum mismatch: {relative}")
    actual_files = {path.relative_to(output).as_posix() for path in output.rglob("*")
                    if path.is_file() and path.name != "SHA256SUMS"}
    if expected_files != actual_files:
        raise ValueError("Checksum inventory differs from bundle files")
    features, targets = read_json(output / "features.json"), read_json(output / "targets.json")
    cases = read_json(ROOT / "data/parallact-recovery/cases.json")["cases"]
    check_records(features, targets, cases)
    provenance = read_json(output / "provenance.json")
    if {item["instance_id"] for item in provenance} != {item["instance_id"] for item in features}:
        raise ValueError("Missing source notices")
    for item in provenance:
        if not (output / item["task_a_terms"]["notice_file"]).is_file():
            raise ValueError("Missing upstream notice")
    print("Verified twelve pairs across eight repositories: seven clean, five conflict.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Check the public bundle without private files or network")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--private", type=Path, default=ROOT / "data/private/parallact/recovery")
    args = parser.parse_args()
    if not args.verify:
        export(args.output, args.private)
    verify(args.output)


if __name__ == "__main__":
    main()
