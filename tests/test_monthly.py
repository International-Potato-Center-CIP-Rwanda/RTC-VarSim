"""Synthetic regression checks for monthly. Temporary fixtures do not require the private research datasets."""
import unittest
import numpy as np
from platform_app.monthly import analysis_months, monthly_similarity


class MonthlyTests(unittest.TestCase):
    def test_periods(self):
        """Verify that periods."""
        self.assertEqual(analysis_months(11,2),[11,12,1,2])
        self.assertEqual(analysis_months(4,4),[4])
        self.assertEqual(analysis_months(1,12),list(range(1,13)))
        for start,end in [(0,2),(1,13),(True,2),(1.0,2)]:
            with self.assertRaises(ValueError):analysis_months(start,end)

    def test_known_rmse_and_weighted_score(self):
        """Verify that known rmse and weighted score."""
        ref=np.zeros((2,12));target=np.zeros((1,2,12))
        target[0,0,:2]=[3,4]  # RMSE sqrt(12.5), not mean absolute error 3.5.
        target[0,1,:2]=[10,10]
        expected=.4*10/(10+np.sqrt(12.5))+.6*50/(50+10)
        self.assertAlmostEqual(monthly_similarity(ref,target,[1,2],[.4,.6],[10,50])[0],expected)
        self.assertEqual(monthly_similarity(ref,ref,[1],[.4,.6],[10,50]),1)

    def test_missing_selected_months(self):
        """Verify that missing selected months."""
        ref=np.zeros((1,12));target=np.zeros((2,1,12));target[0,0,0]=np.nan;target[1,0,5]=np.nan
        score=monthly_similarity(ref,target,[1,2],[1],[10])
        self.assertTrue(np.isnan(score[0]));self.assertEqual(score[1],1)
        ref[0,0]=np.nan
        with self.assertRaises(ValueError):monthly_similarity(ref,target,[1],[1],[10])

    def test_annual_mean_hides_seasonal_difference(self):
        """Verify that annual mean hides seasonal difference."""
        ref=np.array([[0,0,0,0,0,0,20,20,20,20,20,20]])
        target=np.roll(ref,6,axis=-1)
        self.assertEqual(ref.mean(),target.mean())
        self.assertAlmostEqual(monthly_similarity(ref,target,list(range(1,13)),[1],[10]),1/3)

    def test_invalid_inputs(self):
        """Verify that invalid inputs."""
        ref=np.zeros((1,12))
        for months,w,c in [([], [1],[10]),([1,1],[1],[10]),([13],[1],[10]),([1],[.5],[10]),([1],[1],[0])]:
            with self.assertRaises(ValueError):monthly_similarity(ref,ref,months,w,c)
        with self.assertRaises(ValueError):monthly_similarity(ref,np.zeros((1,11)),[1],[1],[10])
