"""Cluster bootstrap: resample whole repositories, not single pairs.

Pairs from one repo are not independent, so resampling pairs would make the
intervals too narrow. Pass `cluster_ids` aligned with the records (usually the
repo names).
"""
import math
import random


def _percentile(sorted_vals, q):
    pos = q * (len(sorted_vals) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _clusters(cluster_ids):
    groups = {}
    for i, c in enumerate(cluster_ids):
        groups.setdefault(c, []).append(i)
    keys = sorted(groups, key=str)
    if len(keys) < 2:
        raise ValueError('bootstrap needs at least two clusters')
    return [groups[k] for k in keys]


def _gather(clusters, picks, values):
    return [values[i] for c in picks for i in clusters[c]]


def _interval(vals, level):
    vals = sorted(vals)
    tail = (1 - level) / 2
    return _percentile(vals, tail), _percentile(vals, 1 - tail)


def cluster_bootstrap(labels, scores, cluster_ids, metric, n_boot=1000, seed=0, level=0.95):
    """Percentile interval for metric(labels, scores) over resampled clusters."""
    clusters = _clusters(cluster_ids)
    rng = random.Random(seed)
    vals, skipped = [], 0
    for _ in range(n_boot):
        picks = [rng.randrange(len(clusters)) for _ in clusters]
        v = metric(_gather(clusters, picks, labels), _gather(clusters, picks, scores))
        if math.isnan(v):
            skipped += 1
        else:
            vals.append(v)
    out = {'point': metric(labels, scores), 'n_clusters': len(clusters),
           'n_valid': len(vals), 'n_skipped': skipped, 'low': None, 'high': None}
    if vals:
        out['low'], out['high'] = _interval(vals, level)
    return out


def paired_difference(labels, scores_a, scores_b, cluster_ids, metric,
                      n_boot=1000, seed=0, level=0.95):
    """Bootstrap metric(A) - metric(B) using the same resampled clusters for both."""
    clusters = _clusters(cluster_ids)
    rng = random.Random(seed)
    diffs, skipped = [], 0
    for _ in range(n_boot):
        picks = [rng.randrange(len(clusters)) for _ in clusters]
        y = _gather(clusters, picks, labels)
        da = metric(y, _gather(clusters, picks, scores_a))
        db = metric(y, _gather(clusters, picks, scores_b))
        if math.isnan(da) or math.isnan(db):
            skipped += 1
        else:
            diffs.append(da - db)
    out = {'point': metric(labels, scores_a) - metric(labels, scores_b),
           'n_clusters': len(clusters), 'n_valid': len(diffs), 'n_skipped': skipped,
           'low': None, 'high': None, 'share_a_better': None}
    if diffs:
        out['low'], out['high'] = _interval(diffs, level)
        out['share_a_better'] = sum(1 for d in diffs if d > 0) / len(diffs)
    return out
