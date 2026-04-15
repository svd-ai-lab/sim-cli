"""Minimal scikit-rf script."""
import json
import skrf as rf
freq = rf.Frequency(1, 10, 11, 'GHz')
print(json.dumps({"ok": True, "n_freq": int(freq.npoints)}))
