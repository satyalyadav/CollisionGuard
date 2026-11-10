"""Leakage-safe splits.

Records that share a repository, a task or a task family are tied into one
group, and a group is never divided between train and test. Because a repo ties
all of its pairs together, this keeps repositories apart, and it also catches
a task (or a family of variants) that appears in more than one repo.
"""
import random


class SplitError(ValueError):
    pass


class LeakageError(AssertionError):
    pass


def _group_indices(records):
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for r in records:
        first = ('repo', r['repo'])
        find(first)
        union(first, ('task', r['task_a']))
        union(first, ('task', r['task_b']))
        if r['family'] is not None:
            union(first, ('family', r['family']))
    groups = {}
    for i, r in enumerate(records):
        groups.setdefault(find(('repo', r['repo'])), []).append(i)
    # Deterministic order, independent of how the union-find happened to root.
    return sorted(groups.values(), key=lambda g: min(records[i]['instance_id'] for i in g))


def assign_groups(records):
    """Return a group number for each record."""
    out = [None] * len(records)
    for number, members in enumerate(_group_indices(records)):
        for i in members:
            out[i] = number
    return out


def take(records, indices):
    return [records[i] for i in indices]


def group_kfold(records, n_splits=5, seed=0):
    """Return [(train_indices, test_indices)] with whole groups per fold.

    Fails loudly when there are fewer groups than folds, instead of quietly
    producing an empty or leaky fold.
    """
    groups = _group_indices(records)
    if n_splits < 2:
        raise SplitError('n_splits must be at least 2')
    if len(groups) < n_splits:
        raise SplitError('%d groups cannot fill %d folds' % (len(groups), n_splits))
    rng = random.Random(seed)
    order = sorted(range(len(groups)), key=lambda g: (-len(groups[g]), rng.random()))
    folds = [[] for _ in range(n_splits)]
    for g in order:
        target = min(range(n_splits), key=lambda f: (len(folds[f]), f))
        folds[target].extend(groups[g])
    result = []
    for f in range(n_splits):
        test = sorted(folds[f])
        in_test = set(test)
        result.append(([i for i in range(len(records)) if i not in in_test], test))
    return result


def holdout_split(records, test_fraction=0.25, seed=0):
    """One train/test split that holds out whole groups."""
    groups = _group_indices(records)
    if len(groups) < 2:
        raise SplitError('need at least two groups to hold one out')
    rng = random.Random(seed)
    order = list(range(len(groups)))
    rng.shuffle(order)
    goal = max(1, round(test_fraction * len(records)))
    test = []
    for n_used, g in enumerate(order):
        if len(test) >= goal or n_used == len(order) - 1:
            break
        test.extend(groups[g])
    in_test = set(test)
    return [i for i in range(len(records)) if i not in in_test], sorted(test)


def forward_time_split(records, cutoff, unseen_repos=False):
    """Train on time < cutoff, test on time >= cutoff.

    Test records that share a task or family with training are dropped, so
    nothing leaks through a repeated task. With unseen_repos=True, test records
    from a repo that also appears in training are dropped too. Returns
    (train_indices, test_indices, dropped) where dropped is [(index, reason)].
    """
    missing = [r['instance_id'] for r in records if r['time'] is None]
    if missing:
        raise SplitError('records without time: %s' % missing[:3])
    train = [i for i, r in enumerate(records) if r['time'] < cutoff]
    tasks = {t for i in train for t in (records[i]['task_a'], records[i]['task_b'])}
    families = {records[i]['family'] for i in train if records[i]['family'] is not None}
    repos = {records[i]['repo'] for i in train}
    test, dropped = [], []
    for i, r in enumerate(records):
        if r['time'] < cutoff:
            continue
        if r['task_a'] in tasks or r['task_b'] in tasks:
            dropped.append((i, 'shared_task'))
        elif r['family'] is not None and r['family'] in families:
            dropped.append((i, 'shared_family'))
        elif unseen_repos and r['repo'] in repos:
            dropped.append((i, 'seen_repo'))
        else:
            test.append(i)
    if not train or not test:
        raise SplitError('cutoff leaves %d train and %d test records' % (len(train), len(test)))
    return train, test, dropped


def assert_no_leakage(train, test, allow_shared_repos=False):
    """Raise LeakageError if train and test share anything they should not.

    Checks instance ids, tasks, families, unordered task pairs and (unless
    allow_shared_repos, for the within-repo forward-time setting) repositories.
    """
    problems = {}

    def check(name, a, b):
        shared = a & b
        if shared:
            problems[name] = sorted(shared)[:3]

    check('instance_id', {r['instance_id'] for r in train}, {r['instance_id'] for r in test})
    check('task',
          {t for r in train for t in (r['task_a'], r['task_b'])},
          {t for r in test for t in (r['task_a'], r['task_b'])})
    check('family',
          {r['family'] for r in train if r['family'] is not None},
          {r['family'] for r in test if r['family'] is not None})
    check('pair',
          {frozenset((r['task_a'], r['task_b'])) for r in train},
          {frozenset((r['task_a'], r['task_b'])) for r in test})
    if not allow_shared_repos:
        check('repo', {r['repo'] for r in train}, {r['repo'] for r in test})
    if problems:
        raise LeakageError('train and test overlap on ' +
                           '; '.join('%s %s' % (k, v) for k, v in sorted(problems.items())))


def split_summary(train, test):
    def one(rs):
        return {'records': len(rs), 'positives': sum(r['label'] for r in rs),
                'repos': len({r['repo'] for r in rs})}
    return {'train': one(train), 'test': one(test)}
