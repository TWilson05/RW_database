"""Merge confirmed duplicate results when the discarded row has no splits."""
import argparse,datetime,json,math
from pathlib import Path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from plan import fetch,digest,numeric

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=int);p.add_argument('target',type=int);args=p.parse_args()
 if args.source==args.target:raise SystemExit('IDs must differ.')
 s=fetch(); old=[(i,r) for i,r in enumerate(s['Results']) if str(r['Result_ID'])==str(args.source)];new=[r for r in s['Results'] if str(r['Result_ID'])==str(args.target)]
 if len(old)!=1 or len(new)!=1:raise SystemExit('Both result IDs must exist uniquely.')
 a=old[0][1];b=new[0]
 for col in ('Athlete_ID','Race_ID','Team_ID','Rank'):
  if str(a.get(col,''))!=str(b.get(col,'')):raise SystemExit(f'{col} differs; review manually.')
 def seconds(r):return sum(numeric(r.get(k,0) or 0)*m for k,m in [('Hour',3600),('Min',60),('Sec',1)])
 x,y=seconds(a),seconds(b)
 if x!=y and not (x==math.ceil(y) or y==math.ceil(x)):raise SystemExit('Marks are not equal or a one-second rounding of each other.')
 if any(str(v['Result_ID'])==str(args.source) for v in s['Splits']):raise SystemExit('Source has splits; transfer and review them before merging.')
 path=Path('secrets/import-backups');path.mkdir(parents=True,exist_ok=True);backup=path/('result-merge-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json');backup.write_text(json.dumps({'snapshot':s,'source':args.source,'target':args.target},ensure_ascii=False,indent=2),encoding='utf-8')
 if digest(fetch())!=digest(s):raise SystemExit('Sheet changed; recheck before retrying.')
 c=Credentials.from_service_account_file(str(next(Path('secrets').glob('*.json'))),scopes=['https://www.googleapis.com/auth/spreadsheets']);api=build('sheets','v4',credentials=c).spreadsheets();sid=Path('secrets/sheet_id.txt').read_text().strip(); meta=api.get(spreadsheetId=sid,fields='sheets(properties(sheetId,title))').execute();sheetid=next(q['properties']['sheetId'] for q in meta['sheets'] if q['properties']['title']=='Results');i=old[0][0]+1
 try:api.batchUpdate(spreadsheetId=sid,body={'requests':[{'deleteDimension':{'range':{'sheetId':sheetid,'dimension':'ROWS','startIndex':i,'endIndex':i+1}}}]}).execute()
 except Exception:print('Write outcome may be unknown. Inspect sheet and backup:',backup);raise
 after=fetch()
 if any(str(r['Result_ID'])==str(args.source) for r in after['Results']) or len([r for r in after['Results'] if str(r['Result_ID'])==str(args.target)])!=1:raise SystemExit('Verification failed; inspect sheet and backup.')
 print(f'Merged result {args.source} into {args.target}; verified. Backup: {backup}')
if __name__=='__main__':main()
