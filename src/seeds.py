"""Seed control (Lab 1). Log the seed as a parameter, never leave it as a comment."""
from __future__ import annotations

import os
import random

import numpy as np

DEFAULT_SEED = 20260920


def set_all(seed: int = DEFAULT_SEED) -> int:
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    # The model takes its own random_state from this value too (src/train.py).
    return seed
