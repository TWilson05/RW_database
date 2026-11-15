import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'importer'))
from check_duplicates import compare

class DuplicateTests(unittest.TestCase):
    def test_date_near_match_flags_differing_result(self):
        snapshot={'Athletes':[{'Athlete_ID':7,'Name':'A Walker'}], 'Races':[{'Race_ID':3,'Date':'1988-10-01','Distance':50,'City':'Seoul','Gender':'Men','Category':'Open'}], 'Results':[{'Result_ID':9,'Athlete_ID':7,'Race_ID':3,'Rank':14,'Hour':3,'Min':48,'Sec':15}]}
        data={'races':[{'race':{'create':True,'Distance':50,'Date':'1988-09-30','City':'Seoul','Gender':'Men','Category':'Open'},'results':[{'athlete':{'id':7},'rank':14,'time':'3:48:15'}]}]}
        result=compare(snapshot,data)
        self.assertEqual(len(result),1)
        self.assertTrue(result[0]['same_mark'])
        self.assertNotEqual(result[0]['input_date'],result[0]['race_date'])

    def test_same_mark_outside_narrow_window_and_different_city(self):
        snapshot={'Athletes':[{'Athlete_ID':7,'Name':'A Walker'}], 'Races':[{'Race_ID':3,'Date':'2014-04-05','Distance':5,'City':'Vancouver'}], 'Results':[{'Result_ID':9,'Athlete_ID':7,'Race_ID':3,'Rank':1,'Hour':0,'Min':19,'Sec':0.92}]}
        data={'races':[{'race':{'create':True,'Distance':5,'Date':'2014-04-15','City':'Burnaby'},'results':[{'athlete':{'id':7},'rank':1,'time':'19:00.92'}]}]}
        result=compare(snapshot,data)
        self.assertEqual(len(result),1)
        self.assertTrue(result[0]['same_mark'])

if __name__=='__main__': unittest.main()
