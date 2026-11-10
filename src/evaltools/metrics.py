"""Metrics for pairwise conflict prediction.

Scores are conflict risk (higher = riskier), labels are 1 for conflict.
Metrics that are undefined (for example AP with no positives) return nan.
"""
import math


def _check(y, s):
    y = [int(v) for v in y]
    s = [float(v) for v in s]
    if not y or len(y) != len(s):
        raise ValueError('labels and scores must be non-empty and the same length')
    if any(v not in (0, 1) for v in y):
        raise ValueError('labels must be 0 or 1')
    if any(math.isnan(v) for v in s):
        raise ValueError('scores contain nan')
    return y, s


def prevalence(y):
    y, _ = _check(y, [0.0] * len(y))
    return sum(y) / len(y)


def _curve(y, s):
    """Cumulative (threshold, tp, fp) at each distinct score, highest first.

    Tied scores move together, so the result does not depend on input order.
    """
    pairs = sorted(zip(s, y), key=lambda t: -t[0])
    tp = fp = i = 0
    out = []
    while i < len(pairs):
        thr = pairs[i][0]
        while i < len(pairs) and pairs[i][0] == thr:
            if pairs[i][1]:
                tp += 1
            else:
                fp += 1
            i += 1
        out.append((thr, tp, fp))
    return out


def average_precision(y, s):
    """Non-interpolated AP: sum over thresholds of (R_n - R_n-1) * P_n."""
    y, s = _check(y, s)
    pos = sum(y)
    if pos == 0:
        return float('nan')
    ap = prev_r = 0.0
    for _, tp, fp in _curve(y, s):
        r = tp / pos
        ap += (r - prev_r) * (tp / (tp + fp))
        prev_r = r
    return ap


def pr_auc_trapezoid(y, s):
    """Area under the PR curve by the trapezoid rule.

    Differs from average_precision; report the two under their own names.
    The curve starts at (recall 0, precision 1) and stops once recall hits 1,
    the same convention as scikit-learn's precision_recall_curve.
    """
    y, s = _check(y, s)
    pos = sum(y)
    if pos == 0:
        return float('nan')
    pts = [(0.0, 1.0)]
    for _, tp, fp in _curve(y, s):
        pts.append((tp / pos, tp / (tp + fp)))
        if tp == pos:
            break
    return sum((r2 - r1) * (p1 + p2) / 2 for (r1, p1), (r2, p2) in zip(pts, pts[1:]))


def precision_at_recall(y, s, min_recall):
    """Best precision among thresholds reaching min_recall: (precision, threshold)."""
    y, s = _check(y, s)
    pos = sum(y)
    if pos == 0:
        return float('nan'), float('nan')
    best = (float('nan'), float('nan'))
    for thr, tp, fp in _curve(y, s):
        if tp / pos >= min_recall and (math.isnan(best[0]) or tp / (tp + fp) > best[0]):
            best = (tp / (tp + fp), thr)
    return best


def recall_at_top_fraction(y, s, fraction):
    """Recall when flagging at most `fraction` of pairs: (recall, number flagged).

    Uses the largest set of top-scored pairs that fits the budget without
    splitting a tie, so the answer never exceeds the budget.
    """
    y, s = _check(y, s)
    pos = sum(y)
    if pos == 0:
        return float('nan'), 0
    budget = math.floor(fraction * len(y))
    tp_best, flagged = 0, 0
    for _, tp, fp in _curve(y, s):
        if tp + fp > budget:
            break
        tp_best, flagged = tp, tp + fp
    return tp_best / pos, flagged


def confusion_at_threshold(y, s, threshold):
    """Flag pairs with score >= threshold and count outcomes."""
    y, s = _check(y, s)
    tp = sum(1 for a, b in zip(y, s) if a == 1 and b >= threshold)
    fp = sum(1 for a, b in zip(y, s) if a == 0 and b >= threshold)
    fn = sum(1 for a, b in zip(y, s) if a == 1 and b < threshold)
    tn = len(y) - tp - fp - fn
    nan = float('nan')
    precision = tp / (tp + fp) if tp + fp else nan
    recall = tp / (tp + fn) if tp + fn else nan
    f1 = 2 * precision * recall / (precision + recall) if tp else (nan if math.isnan(precision) or math.isnan(recall) else 0.0)
    return {'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
            'precision': precision, 'recall': recall, 'f1': f1}


def brier_score(y, s):
    y, s = _check(y, s)
    return sum((a - b) ** 2 for a, b in zip(y, s)) / len(y)


def log_loss(y, s, eps=1e-15):
    y, s = _check(y, s)
    total = 0.0
    for a, b in zip(y, s):
        b = min(max(b, eps), 1 - eps)
        total -= math.log(b) if a else math.log(1 - b)
    return total / len(y)


def reliability_table(y, s, n_bins=5):
    """Equal-width bins over [0, 1]: rows of (low, high, count, mean score, fraction positive)."""
    y, s = _check(y, s)
    if any(b < 0 or b > 1 for b in s):
        raise ValueError('reliability needs scores in [0, 1]')
    bins = [[] for _ in range(n_bins)]
    for a, b in zip(y, s):
        bins[min(int(b * n_bins), n_bins - 1)].append((a, b))
    rows = []
    for k, items in enumerate(bins):
        lo, hi = k / n_bins, (k + 1) / n_bins
        if items:
            rows.append((lo, hi, len(items), sum(b for _, b in items) / len(items),
                         sum(a for a, _ in items) / len(items)))
        else:
            rows.append((lo, hi, 0, None, None))
    return rows


def expected_calibration_error(y, s, n_bins=5):
    rows = reliability_table(y, s, n_bins)
    n = sum(r[2] for r in rows)
    return sum(r[2] / n * abs(r[3] - r[4]) for r in rows if r[2])
