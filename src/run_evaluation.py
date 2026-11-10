"""Evaluate the starting baselines on the public twelve-pair dataset.

    python src/run_evaluation.py

Scores come from run_baselines.py (leave-one-repository-out). This script checks
that those folds leak nothing, then reports metrics on the pairs that received
a score. Twelve pairs cannot establish prediction accuracy; treat the numbers as
a check that the workflow runs.
"""
import argparse
import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaltools import splits
from evaltools.report import evaluate, format_report, prevalence_scores
from evaltools.schema import normalize_records
from run_baselines import (_folds, join_data, load_data,
                           run_logistic_baseline, run_tfidf_baseline)


def build_records(features, pairs, labels, repos, ids):
    # Repository names are case-insensitive on the hosting service, as in run_baselines.
    return normalize_records([
        {'instance_id': iid, 'repo': repo[0].casefold(), 'task_a': a, 'task_b': b, 'label': label}
        for iid, (a, b), repo, label in zip(ids, pairs, repos, labels)])


def audit_folds(records, repos):
    """Raise LeakageError if any leave-one-repository-out fold shares a repo or task."""
    count = 0
    for train, test in _folds(repos):
        splits.assert_no_leakage(splits.take(records, train), splits.take(records, test))
        count += 1
    return count


def evaluate_scores(name, records, scores, calibrated, n_boot):
    covered = [i for i, s in enumerate(scores) if s is not None]
    print('\n%s: %d of %d pairs were scored' % (name, len(covered), len(records)))
    kept = splits.take(records, covered)
    if len({r['repo'] for r in kept}) < 2:
        print('not enough scored repositories to evaluate')
        return
    print(format_report(evaluate(kept, [scores[i] for i in covered], n_boot=n_boot,
                                 calibrated=calibrated), name))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic', action='store_true', help='use the built-in invented examples')
    parser.add_argument('--n-boot', type=int, default=500)
    args = parser.parse_args(argv)

    features, targets, source = load_data(args.synthetic)
    pairs, labels, repos, ids = join_data(features, targets)
    records = build_records(features, pairs, labels, repos, ids)
    print('Data source: %s; %d pairs, %d positives' % (source, len(records), sum(labels)))
    print('Demo only: this small dataset does not establish prediction accuracy.')
    print('Leakage audit passed for %d leave-one-repository-out folds.' % audit_folds(records, repos))

    quiet = io.StringIO()  # the baseline runner prints every pair; keep this report short
    with contextlib.redirect_stdout(quiet):
        tfidf = run_tfidf_baseline(pairs, labels, repos, ids)
        logistic = run_logistic_baseline(pairs, labels, repos, ids)
    prevalence = [None] * len(records)
    for train, test in _folds(repos):
        if train:
            for i, s in zip(test, prevalence_scores(splits.take(records, train), splits.take(records, test))):
                prevalence[i] = s

    evaluate_scores('base-rate reference', records, prevalence, True, args.n_boot)
    # Cosine similarity is not a probability, so calibration metrics are left out.
    evaluate_scores('TF-IDF cosine', records, tfidf, False, args.n_boot)
    evaluate_scores('logistic regression', records, logistic, True, args.n_boot)


if __name__ == '__main__':
    main()
