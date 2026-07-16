"""C033 spike: trace report_progress events at owner actual scale."""
import sys, time
sys.path.insert(0, 'E:/DEMO/DataAnalysis/projects/dateanalysis-desktop')
from app.services.head_tail_attribution import build_head_tail_report
import numpy as np, pandas as pd

rng = np.random.default_rng(0)
n = 640_000
p = 4
t = pd.date_range('2024-01-01', periods=n, freq='1min')
cols = {'时间': t}
for j in range(p - 1):
    cols['[机头]f' + str(j+1)] = rng.normal(50, 5, n)
target = np.clip(
    np.round(4.0 + 0.3 * (cols['[机头]f1'] - 50) + rng.normal(0, 0.4, n)),
    1, 8,
).astype(int)
cols['[机尾]指数-s'] = target
df = pd.DataFrame(cols)
feats = ['[机头]f' + str(j+1) for j in range(p - 1)]
events = []
t_start = [None]

def cb(pct, msg):
    if t_start[0] is None:
        t_start[0] = time.perf_counter()
    events.append((time.perf_counter() - t_start[0], pct, msg))

t0 = time.perf_counter()
out = build_head_tail_report(
    df, target_col='[机尾]指数-s', feature_cols=feats,
    min_samples=10, multi=True, use_pingouin=False,
    report_progress=cb,
)
print('Total wall: {:.3f}s, events={}'.format(time.perf_counter() - t0, len(events)))
for ts, pct, msg in events:
    print('  t={:.3f}s pct={:3d} msg={}'.format(ts, pct, msg))

multi = out.get('multi', {})
if multi:
    print()
    print('M1 rows:', len(multi.get('partial_corr', [])))
    ols = multi.get('ols') or {}
    print('M2 k:', ols.get('k'), 'r2:', round(ols.get('r2', 0), 4))
    print('M2 warnings count:', len(multi.get('warnings', [])))
