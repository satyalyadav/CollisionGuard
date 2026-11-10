"""One call that turns records plus scores into a full evaluation."""
import math

from . import metrics as m
from .bootstrap import cluster_bootstrap
from .schema import align_scores


def prevalence_scores(train, test):
    """Placeholder baseline: every test pair gets the training conflict rate."""
    rate = sum(r['label'] for r in train) / len(train)
    return [rate] * len(test)


def evaluate(records, scores, threshold=0.5, min_recall=0.5, budget=0.2, n_boot=500, seed=0,
             calibrated=True):
    """Evaluate scores against labels.

    Set calibrated=False for scores that are not probabilities (for example a raw
    similarity), so Brier score, log loss and calibration are left out.
    """
    scores = align_scores(records, scores)
    y = [r['label'] for r in records]
    repos = [r['repo'] for r in records]
    warnings = []
    n_repos = len(set(repos))
    if n_repos < 10:
        warnings.append('only %d repositories: bootstrap intervals are unstable' % n_repos)
    if sum(y) < 20:
        warnings.append('only %d positives: treat every metric as a demonstration' % sum(y))
    per_repo = {}
    for repo in sorted(set(repos)):
        ys = [a for a, r in zip(y, repos) if r == repo]
        ss = [b for b, r in zip(scores, repos) if r == repo]
        per_repo[repo] = {'n': len(ys), 'positives': sum(ys), 'ap': m.average_precision(ys, ss)}
        if sum(ys) == 0:
            warnings.append('repo %s has no positives, so its AP is undefined' % repo)
    p_at_r, p_thr = m.precision_at_recall(y, scores, min_recall)
    r_at_budget, flagged = m.recall_at_top_fraction(y, scores, budget)
    in_unit = calibrated and all(0 <= s <= 1 for s in scores)
    return {
        'n': len(y), 'positives': sum(y), 'prevalence': m.prevalence(y), 'n_repos': n_repos,
        'average_precision': m.average_precision(y, scores),
        'ap_interval': cluster_bootstrap(y, scores, repos, m.average_precision, n_boot, seed),
        'pr_auc_trapezoid': m.pr_auc_trapezoid(y, scores),
        'precision_at_recall': {'min_recall': min_recall, 'precision': p_at_r, 'threshold': p_thr},
        'recall_at_budget': {'budget': budget, 'recall': r_at_budget, 'flagged': flagged},
        'confusion': dict(m.confusion_at_threshold(y, scores, threshold), threshold=threshold),
        'brier': m.brier_score(y, scores) if in_unit else float('nan'),
        'log_loss': m.log_loss(y, scores) if in_unit else float('nan'),
        'ece': m.expected_calibration_error(y, scores) if in_unit else float('nan'),
        'reliability': m.reliability_table(y, scores) if in_unit else [],
        'per_repo': per_repo,
        'warnings': warnings,
    }


def _f(v):
    return 'n/a' if v is None or (isinstance(v, float) and math.isnan(v)) else '%.3f' % v


def format_report(result, name='model'):
    ci = result['ap_interval']
    c = result['confusion']
    lines = [
        '== %s ==' % name,
        'pairs %d, positives %d, repos %d, prevalence %s' % (
            result['n'], result['positives'], result['n_repos'], _f(result['prevalence'])),
        'average precision %s  (95%% interval %s to %s over %d repo clusters)' % (
            _f(result['average_precision']), _f(ci['low']), _f(ci['high']), ci['n_clusters']),
        'PR-AUC (trapezoid) %s' % _f(result['pr_auc_trapezoid']),
        'precision at recall >= %.2f: %s' % (
            result['precision_at_recall']['min_recall'], _f(result['precision_at_recall']['precision'])),
        'recall when flagging top %d%%: %s' % (
            round(100 * result['recall_at_budget']['budget']), _f(result['recall_at_budget']['recall'])),
        'at threshold %.2f: tp %d fp %d tn %d fn %d, precision %s recall %s f1 %s' % (
            c['threshold'], c['tp'], c['fp'], c['tn'], c['fn'],
            _f(c['precision']), _f(c['recall']), _f(c['f1'])),
        'Brier %s  log loss %s  ECE %s' % (_f(result['brier']), _f(result['log_loss']), _f(result['ece'])),
    ]
    lines += ['warning: ' + w for w in result['warnings']]
    return '\n'.join(lines)
