"""Strict, bounded-memory monthly normal calculation for one spatial tile."""
import numpy as np


class MonthlyNormal:
    def __init__(self, shape):
        """Initialize MonthlyNormal from its supplied inputs without starting the application server."""
        self.total = np.zeros(shape, dtype='float64')
        self.count = np.zeros(shape, dtype='uint8')
        self.years = set()

    def add(self, year, values):
        """Add a validated annual masked raster to the monthly accumulator; reject repeated or out-of-period years."""
        if year not in range(1991, 2021) or year in self.years:
            raise ValueError('Expected a distinct year in 1991–2020')
        values = np.ma.asarray(values, dtype='float64')
        if values.shape != self.total.shape:
            raise ValueError('Tile shape mismatch')
        valid = ~np.ma.getmaskarray(values) & np.isfinite(values.data)
        self.total[valid] += values.data[valid]
        self.count[valid] += 1
        self.years.add(year)

    def finish(self):
        """Return the thirty-year mean and valid-year counts, masking pixels with incomplete annual coverage."""
        if self.years != set(range(1991, 2021)):
            raise ValueError('All thirty years are required')
        return np.ma.array(self.total / 30, mask=self.count != 30), self.count.copy()
