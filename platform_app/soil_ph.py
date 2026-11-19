"""Soil pH layer aggregation helpers."""

import numpy as np


def thickness_weighted_ph(layer_0_5, layer_5_15, layer_15_30):
    """Combine pH layers by thickness; missing input in any layer stays missing."""
    arrays = [np.asarray(layer, dtype="float32") for layer in (layer_0_5, layer_5_15, layer_15_30)]
    if any(array.shape != arrays[0].shape for array in arrays[1:]):
        raise ValueError("All pH layers must have the same shape.")
    valid = np.logical_and.reduce([np.isfinite(array) for array in arrays])
    result = np.full(arrays[0].shape, np.nan, dtype="float32")
    if np.any(valid):
        result[valid] = (5 * arrays[0][valid] + 10 * arrays[1][valid] + 15 * arrays[2][valid]) / 30
    return result
