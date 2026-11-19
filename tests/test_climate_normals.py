"""Synthetic regression checks for climate normals. Temporary fixtures do not require the private research datasets."""
import unittest
import numpy as np
from climate_normals import MonthlyNormal


class NormalTests(unittest.TestCase):
    def test_mean_and_missing_year_mask(self):
        """Verify that mean and missing year mask."""
        normal = MonthlyNormal((3,))
        for year in range(1991, 2021):
            normal.add(year, np.ma.array([year-1990, 120, float('nan')], mask=[False, year==2000, False]))
        result, counts = normal.finish()
        self.assertEqual(result[0], 15.5)
        self.assertEqual(counts.tolist(), [30,29,0])
        self.assertEqual(result.mask.tolist(), [False,True,True])

    def test_rainfall_is_mean_not_thirty_year_sum(self):
        """Verify that rainfall is mean not thirty year sum."""
        normal = MonthlyNormal((1,))
        for year in range(1991, 2021): normal.add(year, [100])
        self.assertEqual(normal.finish()[0][0], 100)

    def test_incomplete_and_duplicate_years_rejected(self):
        """Verify that incomplete and duplicate years rejected."""
        normal = MonthlyNormal((1,))
        normal.add(1991, [10])
        with self.assertRaises(ValueError): normal.add(1991, [10])
        with self.assertRaises(ValueError): normal.finish()
