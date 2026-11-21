"""Made-up data for exercising the evaluation tools. Not real results."""
import random


def make_synthetic_records(n_repos=8, pairs_per_repo=6, conflict_rate=0.3, seed=0):
    """Fake task pairs. Tasks repeat inside a repo, as in real data, and some
    tasks belong to a family of variants."""
    rng = random.Random(seed)
    rows = []
    for r in range(n_repos):
        pool = ['repo%d-task%d' % (r, k) for k in range(pairs_per_repo // 2 + 3)]
        for k in range(pairs_per_repo):
            a, b = rng.sample(pool, 2)
            rows.append({
                'instance_id': 'repo%d-pair%d' % (r, k),
                'repo': 'repo%d' % r,
                'task_a_id': a,
                'task_b_id': b,
                'family': 'repo%d-fam%d' % (r, int(a.split('task')[1]) % 2),
                'label': int(rng.random() < conflict_rate),
                'time': r * pairs_per_repo + k,
            })
    return rows


def make_synthetic_scores(records, signal=0.3, seed=0):
    """Scores in [0, 1]. signal=0 is pure noise; larger values separate conflicts."""
    rng = random.Random(seed)
    return [min(1.0, max(0.0, 0.35 + signal * r['label'] + rng.gauss(0, 0.2))) for r in records]
