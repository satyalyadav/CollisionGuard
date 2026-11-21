"""Run the evaluation tools end to end on made-up data.

    python scripts/eval_demo.py

Everything here is synthetic. The numbers show that the tools work, not how
well any CollisionGuard model performs.
"""
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaltools import splits
from evaltools.bootstrap import paired_difference
from evaltools.metrics import average_precision
from evaltools.report import evaluate, format_report, prevalence_scores
from evaltools.schema import normalize_records
from evaltools.synthetic import make_synthetic_records, make_synthetic_scores


def main():
    records = normalize_records(make_synthetic_records(n_repos=10, pairs_per_repo=8, seed=7))

    # 1. A naive random split leaks repos and tasks. The checker should catch it.
    shuffled = list(range(len(records)))
    random.Random(0).shuffle(shuffled)
    cut = len(records) // 4
    try:
        splits.assert_no_leakage(splits.take(records, shuffled[cut:]), splits.take(records, shuffled[:cut]))
        print('random split: no leak found (unexpected)')
    except splits.LeakageError as err:
        print('random split is rejected as expected:', err)

    # 2. Grouped folds pass the same check. Collect out-of-fold scores.
    flat = {}
    for train, test in splits.group_kfold(records, n_splits=5, seed=0):
        tr, te = splits.take(records, train), splits.take(records, test)
        splits.assert_no_leakage(tr, te)
        flat.update(zip((r['instance_id'] for r in te), prevalence_scores(tr, te)))
    print('\ngrouped folds: no leakage in any of 5 folds\n')

    # 3. Score two stand-in models and compare them with a paired bootstrap.
    prevalence = [flat[r['instance_id']] for r in records]
    fake_model = make_synthetic_scores(records, signal=0.4, seed=1)
    print(format_report(evaluate(records, prevalence, seed=0), 'prevalence baseline'))
    print()
    print(format_report(evaluate(records, fake_model, seed=0), 'made-up model'))
    diff = paired_difference([r['label'] for r in records], fake_model, prevalence,
                             [r['repo'] for r in records], average_precision, n_boot=500, seed=0)
    print('\nAP difference (model - baseline): %.3f, 95%% interval %.3f to %.3f, '
          'model better in %.0f%% of resamples' % (
              diff['point'], diff['low'], diff['high'], 100 * diff['share_a_better']))


if __name__ == '__main__':
    main()
