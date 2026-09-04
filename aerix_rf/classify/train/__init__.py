"""Stage-2 classifier *training* pipeline.

Kept import-light on purpose: importing this package (and ``features``/``data``)
pulls in only numpy + the box's own DSP, NOT scikit-learn/joblib. That lets
``aerix_rf.classify.model`` reuse the exact feature extractor at inference time
without dragging the (optional) ``train`` dependency group into the box runtime.

Only ``train.py`` touches scikit-learn, and only when you actually train.
"""
