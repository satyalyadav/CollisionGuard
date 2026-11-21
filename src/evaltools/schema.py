"""Record contract shared by the evaluation tools.

A record describes one task pair. The names follow docs/data/local-record-format.md.
Predictions are separate: a score per record, higher meaning more conflict risk.
"""
import hashlib


class SchemaError(ValueError):
    pass


def task_id(text):
    """Stable id for a task statement (SHA-256 of the stripped UTF-8 text)."""
    return hashlib.sha256(text.strip().encode('utf-8')).hexdigest()


def normalize_label(value):
    """Map 'conflict'/'clean' (or 1/0, True/False) to 1/0."""
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ('conflict', '1', 'true'):
            return 1
        if v in ('clean', '0', 'false'):
            return 0
    elif value in (0, 1):
        return int(value)
    raise SchemaError('unrecognized label: %r' % (value,))


def _task(row, side, index):
    if 'task_%s_id' % side in row:
        return str(row['task_%s_id' % side])
    if 'task_%s' % side in row:
        return task_id(row['task_%s' % side])
    raise SchemaError('row %d needs task_%s_id or task_%s' % (index, side, side))


def normalize_records(rows):
    """Validate rows and return clean dicts.

    Required: instance_id, repo, label, and each task as text (task_a, task_b)
    or as an id (task_a_id, task_b_id). Optional: family (variants of one task
    that must stay together) and time (anything comparable, used only for
    forward-time splits).
    """
    out, seen = [], set()
    for i, row in enumerate(rows):
        for key in ('instance_id', 'repo', 'label'):
            if key not in row:
                raise SchemaError('row %d is missing %r' % (i, key))
        iid = str(row['instance_id'])
        if iid in seen:
            raise SchemaError('duplicate instance_id %r' % iid)
        seen.add(iid)
        a, b = _task(row, 'a', i), _task(row, 'b', i)
        if a == b:
            raise SchemaError('%s pairs a task with itself' % iid)
        family = row.get('family')
        out.append({
            'instance_id': iid,
            'repo': str(row['repo']),
            'task_a': a,
            'task_b': b,
            'label': normalize_label(row['label']),
            'family': None if family is None else str(family),
            'time': row.get('time'),
        })
    return out


def join_features_targets(features, targets):
    """Join the private features.json and targets.json records on instance_id."""
    f_ids = [str(r['instance_id']) for r in features]
    t_ids = [str(r['instance_id']) for r in targets]
    if len(set(f_ids)) != len(f_ids) or len(set(t_ids)) != len(t_ids):
        raise SchemaError('duplicate instance_id in features or targets')
    if set(f_ids) != set(t_ids):
        raise SchemaError('feature and target ids do not match')
    by_id = {str(t['instance_id']): t for t in targets}
    rows = []
    for f in features:
        row = dict(f)
        row['label'] = by_id[str(f['instance_id'])]['label']
        rows.append(row)
    return normalize_records(rows)


def align_scores(records, scores):
    """Accept a list aligned with records or a dict keyed by instance_id."""
    if isinstance(scores, dict):
        missing = [r['instance_id'] for r in records if r['instance_id'] not in scores]
        if missing:
            raise SchemaError('no score for %s' % missing[:3])
        return [float(scores[r['instance_id']]) for r in records]
    scores = [float(s) for s in scores]
    if len(scores) != len(records):
        raise SchemaError('got %d scores for %d records' % (len(scores), len(records)))
    return scores
