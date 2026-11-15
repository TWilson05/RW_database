import unittest
from importer.plan import HEADERS, key, mark, plan

def snapshot():
    return {
        'Athletes': [{'Athlete_ID':1,'Name':'José Example','Gender':'Male','YOB':'','Nationality':'CAN','Prov':'','Note':''}],
        'Teams': [{'Team_ID':0,'Name':'Unattached','Aliases':'Solo; Independent','Prov':'','Country':''}],
        'Races': [{'Race_ID':1,'Distance':20,'Date':'2024-01-01','City':'X','Prov':'','Country':'CAN','Surface':'Road','Meet':'','Gender':'Men','Category':'Open','Timing':'','Notes':''}],
        'Results': [], 'Splits': []}

def entry():
    return {'source':'example', 'results':[{'athlete':{'Name':'Jose Example','YOB':1990},'team':{'Name':'Solo'},'race':{'id':1},'rank':1,'time':'1:30:00','splits':[{'distance':10,'time':'45:00'}]}]}

class ImportTests(unittest.TestCase):
    def test_accent_alias_missing_update_and_split(self):
        p=plan(snapshot(),entry())
        self.assertEqual(p['errors'],[])
        self.assertEqual([x['table'] for x in p['operations']],['Athletes','Results','Splits'])
        self.assertEqual(p['operations'][0]['fields'],{'YOB':1990})
    def test_duplicate_is_idempotent(self):
        s=snapshot(); e=entry(); s['Athletes'][0]['YOB']=1990
        s['Results']=[{'Result_ID':1,'Athlete_ID':1,'Team_ID':0,'Race_ID':1,'Rank':1,'Hour':1,'Min':30,'Sec':0}]
        s['Splits']=[{'Result_ID':1,'Distance':10,'Hour':0,'Min':45,'Sec':0}]
        p=plan(s,e); self.assertEqual(p['errors'],[]); self.assertEqual(p['operations'],[])
    def test_uncertain_and_impossible(self):
        e=entry(); e['results'][0]['athlete']={'Name':'Joz Example'}
        self.assertTrue(plan(snapshot(),e)['errors'])
        e=entry(); e['results'][0]['time']='5:00'
        self.assertTrue(plan(snapshot(),e)['errors'])
    def test_multiple_exact_names_require_decision(self):
        s=snapshot(); s['Athletes'].append(dict(s['Athletes'][0],Athlete_ID=2))
        self.assertTrue(plan(s,entry())['errors'])
    def test_conflicting_existing(self):
        s=snapshot(); s['Athletes'][0]['YOB']=1985
        self.assertTrue(plan(s,entry())['errors'])
    def test_shared_new_race_is_created_once(self):
        e=entry(); first=e['results'][0]
        first['race']={'create':True,'Distance':20,'Surface':'Road','Date':'2025-01-01'}
        second=dict(first, athlete={'create':True,'Name':'Other Athlete','Gender':'Male'}, time='1:35:00', splits=[])
        e['results'].append(second)
        p=plan(snapshot(),e)
        self.assertEqual(p['errors'],[])
        self.assertEqual(len([op for op in p['operations'] if op['table']=='Races']),1)
    def test_grouped_races_and_existing_race_detection(self):
        e=entry(); result=e['results'][0]; race=result.pop('race')
        grouped={'source':'example','races':[{'race':race,'results':[result]}]}
        p=plan(snapshot(),grouped)
        self.assertEqual(p['errors'],[])
        self.assertEqual(plan(snapshot(),p['input']),p)
        grouped['races'][0]['race']={'create':True,'Distance':20,'Surface':'Road','Date':'2024-01-01','City':'X'}
        self.assertTrue(plan(snapshot(),grouped)['errors'])
    def test_confirmed_name_correction_checks_previous_value(self):
        e=entry(); e['results'][0]['athlete']={'id':1,'corrections':{'Name':{'from':'José Example','to':'Jose Corrected'}}}
        p=plan(snapshot(),e)
        self.assertEqual(p['errors'],[])
        self.assertEqual(p['operations'][0]['fields']['Name'],'Jose Corrected')
        e['results'][0]['athlete']['corrections']['Name']['from']='wrong'
        self.assertTrue(plan(snapshot(),e)['errors'])
    def test_metadata_only_update_and_alias_deduplication(self):
        p=plan(snapshot(),{'updates':[{'table':'Teams','record':{'id':0,'add_aliases':['Independent','No club']}}]})
        self.assertEqual(p['errors'],[])
        self.assertEqual(p['operations'][0]['fields']['Aliases'],'Solo, Independent, No club')
        p=plan(snapshot(),{'updates':[{'table':'Athletes','record':{'id':1,'YOB':1990}}]})
        self.assertEqual(p['operations'][0]['fields'],{'YOB':1990})
    def test_result_correction_and_unknown_time(self):
        s=snapshot()
        s['Results']=[{'Result_ID':7,'Athlete_ID':1,'Team_ID':0,'Race_ID':1,'Rank':2,'Hour':0,'Min':0,'Sec':0}]
        p=plan(s,{'updates':[{'table':'Results','record':{'id':7,'corrections':{'Rank':{'from':2,'to':3}}}}]})
        self.assertEqual(p['errors'],[])
        self.assertEqual(p['operations'][0]['fields']['Rank'],3)
        e=entry(); e['results'][0].pop('time'); e['results'][0]['no_time']=True; e['results'][0]['splits']=[]
        self.assertFalse(plan(snapshot(),e)['errors'])
    def test_race_category_difference_requires_confirmation(self):
        e=entry(); e['results'][0]['race']={'create':True,'Distance':20,'Surface':'Road','Date':'2024-01-01','City':'X','Gender':'Men','Category':'Junior'}
        self.assertTrue(plan(snapshot(),e)['errors'])
        e['results'][0]['race']['confirm_distinct']=True
        self.assertFalse(plan(snapshot(),e)['errors'])
    def test_same_mark_different_race_and_date_requires_review(self):
        s=snapshot()
        s['Results']=[{'Result_ID':7,'Athlete_ID':1,'Team_ID':0,'Race_ID':1,'Rank':1,'Hour':1,'Min':30,'Sec':0}]
        e=entry(); e['results'][0]['race']={'create':True,'Distance':20,'Surface':'Road','Date':'2024-01-11','City':'Different'}
        self.assertTrue(any('possible duplicate results' in x for x in plan(s,e)['errors']))
        e['results'][0]['confirm_distinct_result']=True
        self.assertFalse(plan(s,e)['errors'])
    def test_new_canadian_race_requires_province(self):
        e=entry(); e['results'][0]['race']={'create':True,'Distance':20,'Surface':'Road','Date':'2025-01-01','City':'Victoria','Country':'CAN'}
        self.assertTrue(any('province abbreviation' in x for x in plan(snapshot(),e)['errors']))
        e['results'][0]['race']['Prov']='BC'
        self.assertFalse(plan(snapshot(),e)['errors'])

if __name__=='__main__': unittest.main()
