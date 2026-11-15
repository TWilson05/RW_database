"""Merge two confirmed duplicate athlete IDs, preserving referenced results."""
import argparse, datetime, json
from pathlib import Path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from plan import fetch, digest, key


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('source',type=int); p.add_argument('target',type=int); args=p.parse_args()
    if args.source==args.target: raise SystemExit('IDs must differ.')
    snapshot=fetch(); rows=snapshot['Athletes']
    old=[(i,r) for i,r in enumerate(rows) if str(r['Athlete_ID'])==str(args.source)]
    new=[(i,r) for i,r in enumerate(rows) if str(r['Athlete_ID'])==str(args.target)]
    if len(old)!=1 or len(new)!=1: raise SystemExit('Athlete IDs must both exist uniquely.')
    src=old[0][1]; dst=new[0][1]
    for col in ('Name','Gender','YOB','Nationality','Prov','Note'):
        if src.get(col) and (not dst.get(col) or (key(src[col])!=key(dst[col]))):
            raise SystemExit(f'Source {col} is missing or different in target; preserve it before merging.')
    source_results=[(i,r) for i,r in enumerate(snapshot['Results']) if str(r['Athlete_ID'])==str(args.source)]
    target_races={str(r['Race_ID']) for r in snapshot['Results'] if str(r['Athlete_ID'])==str(args.target)}
    if any(str(r['Race_ID']) in target_races for _,r in source_results): raise SystemExit('Athletes have results in the same race; review duplicates first.')
    backupdir=Path('secrets/import-backups'); backupdir.mkdir(parents=True,exist_ok=True)
    backup=backupdir / ('merge-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    backup.write_text(json.dumps({'snapshot':snapshot,'source':args.source,'target':args.target},ensure_ascii=False,indent=2),encoding='utf-8')
    if digest(fetch())!=digest(snapshot): raise SystemExit('Sheet changed; recheck before retrying.')
    creds=Credentials.from_service_account_file(str(next(Path('secrets').glob('*.json'))),scopes=['https://www.googleapis.com/auth/spreadsheets'])
    service=build('sheets','v4',credentials=creds).spreadsheets(); sid=Path('secrets/sheet_id.txt').read_text().strip()
    meta=service.get(spreadsheetId=sid,fields='sheets(properties(sheetId,title))').execute()
    ids={x['properties']['title']:x['properties']['sheetId'] for x in meta['sheets']}
    requests=[]
    for index,_ in source_results:
        requests.append({'updateCells':{'range':{'sheetId':ids['Results'],'startRowIndex':index+1,'endRowIndex':index+2,'startColumnIndex':1,'endColumnIndex':2},'rows':[{'values':[{'userEnteredValue':{'numberValue':args.target}}]}],'fields':'userEnteredValue'}})
    requests.append({'deleteDimension':{'range':{'sheetId':ids['Athletes'],'dimension':'ROWS','startIndex':old[0][0]+1,'endIndex':old[0][0]+2}}})
    try: service.batchUpdate(spreadsheetId=sid,body={'requests':requests}).execute()
    except Exception:
        print('Write outcome may be unknown. Inspect sheet and backup before retrying:',backup); raise
    after=fetch()
    if any(str(r['Athlete_ID'])==str(args.source) for r in after['Athletes']+after['Results']): raise SystemExit('Merge verification failed; inspect backup and sheet.')
    before_ids={str(r['Result_ID']) for _,r in source_results}
    after_ids={str(r['Result_ID']) for r in after['Results'] if str(r['Athlete_ID'])==str(args.target)}
    if not before_ids.issubset(after_ids): raise SystemExit('Result verification failed; inspect backup and sheet.')
    print(f'Merged athlete {args.source} into {args.target}; transferred {len(source_results)} results. Verified. Backup: {backup}')

if __name__=='__main__': main()
