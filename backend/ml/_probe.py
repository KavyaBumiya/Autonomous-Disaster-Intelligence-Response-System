import numpy as np
from ml import hazards as hz, train as tr

d = tr.load_dataset(hz.FLOOD)
folds = tr._fold_assignment(d)
ramp = tr.rules_baseline_scores(hz.FLOOD, d)
cols = list(d.columns)

def per_fold_auc(score):
    vals = []
    for f in range(tr.CV_FOLDS):
        m = folds == f
        if m.sum() < 2 or len(set(d.y[m].tolist())) < 2: continue
        a = tr.roc_auc(d.y[m], np.asarray(score)[m])
        if np.isfinite(a): vals.append(a)
    return float(np.mean(vals)), len(vals)

def oof(idx):
    x = d.x[:, idx]
    out = np.full(len(d), np.nan)
    for f in range(tr.CV_FOLDS):
        trm, tem = folds != f, folds == f
        if not tem.any() or len(set(d.y[trm].tolist())) < 2: continue
        xt, m_, s_ = tr._standardise(x[trm])
        c, b = tr.fit_logistic(xt, d.y[trm])
        out[tem] = tr.predict_proba((x[tem]-m_)/s_, c, b)
    return out

idxs = [cols.index(c) for c in cols]
model = oof(idxs)

print("POOLED out-of-fold AUC (what the artifact currently reports):")
print(f"   model              {tr.roc_auc(d.y, model):.4f}")
print(f"   rules ramp         {tr.roc_auc(d.y, ramp):.4f}")
print()
print("PER-FOLD average AUC (removes cross-fold calibration drift):")
m,_ = per_fold_auc(model); print(f"   model              {m:.4f}")
r,_ = per_fold_auc(ramp);  print(f"   rules ramp         {r:.4f}")
print()
pk = d.x[:, cols.index('peak_precip_3d_mm')]
p10 = d.x[:, cols.index('precip_10d_mm')]
m,_ = per_fold_auc(pk); print(f"   peak_precip_3d_mm  {m:.4f}   (raw single feature)")
m,_ = per_fold_auc(p10); print(f"   precip_10d_mm      {m:.4f}   (raw single feature)")
