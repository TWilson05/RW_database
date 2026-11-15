"""Apply a reviewed import plan to the configured Google Sheet."""
import argparse
import datetime
import json
from pathlib import Path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from plan import HEADERS, IDS, digest, fetch, plan


def build_changes(snapshot, operations):
    positions={table:{str(row[IDS[table]]):i+2 for i,row in enumerate(rows)} for table,rows in snapshot.items() if table in IDS}
    data=[]
    def cell_value(field,value):
        if field.endswith('_ID') and value != '':
            try: return int(value)
            except (ValueError, TypeError): raise ValueError(f'Invalid numeric ID: {value!r}')
        return value
    next_row={table:len(rows)+2 for table,rows in snapshot.items()}
    for op in operations:
        table=op['table']; headers=HEADERS[table]
        if op['action']=='append':
            row=op['row']; index=next_row[table]; next_row[table]+=1
            if table in IDS: positions[table][str(row[IDS[table]])]=index
            last=chr(ord('A')+len(headers)-1)
            data.append({'range':f"'{table}'!A{index}:{last}{index}",'values':[[cell_value(h,row.get(h,'')) for h in headers]]})
        elif op['action']=='update':
            index=positions[table][str(op['id'])]
            for field,value in op['fields'].items():
                column=chr(ord('A')+headers.index(field))
                data.append({'range':f"'{table}'!{column}{index}",'values':[[cell_value(field,value)]]})
        else: raise ValueError('Unknown operation')
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path)
    args=parser.parse_args()
    proposal=json.loads(args.plan.read_text(encoding='utf-8-sig'))
    if proposal.get('errors'): raise SystemExit('Plan has unresolved errors. Nothing was written.')
    snapshot=fetch()
    if digest(snapshot)!=proposal.get('snapshot_sha256'): raise SystemExit('Sheet changed since planning. Replan and review; nothing was written.')
    expected=plan(snapshot,proposal['input'])
    if expected!=proposal: raise SystemExit('Plan does not match a fresh calculation. Replan and review; nothing was written.')
    changes=build_changes(snapshot,proposal['operations'])
    if not changes:
        print('No changes needed.'); return
    backupdir=Path('secrets/import-backups'); backupdir.mkdir(parents=True,exist_ok=True)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=backupdir / f'import-{stamp}.json'
    backup.write_text(json.dumps({'snapshot':snapshot,'plan':proposal},ensure_ascii=False,indent=2),encoding='utf-8')
    if digest(fetch())!=proposal['snapshot_sha256']: raise SystemExit('Sheet changed during preparation. Nothing was written.')
    creds=Credentials.from_service_account_file(str(next(Path('secrets').glob('*.json'))),scopes=['https://www.googleapis.com/auth/spreadsheets'])
    service=build('sheets','v4',credentials=creds).spreadsheets()
    sid=Path('secrets/sheet_id.txt').read_text().strip()
    meta=service.get(spreadsheetId=sid,fields='sheets(properties(sheetId,title,gridProperties(rowCount)))').execute()
    properties={s['properties']['title']:s['properties'] for s in meta['sheets']}
    resizes=[]
    for table in HEADERS:
        added=sum(op['action']=='append' and op['table']==table for op in proposal['operations'])
        needed=1+len(snapshot[table])+added
        current=properties[table]['gridProperties']['rowCount']
        if needed>current:
            resizes.append({'appendDimension':{'sheetId':properties[table]['sheetId'],'dimension':'ROWS','length':max(needed-current,100)}})
    if resizes:
        try: service.batchUpdate(spreadsheetId=sid,body={'requests':resizes}).execute()
        except Exception:
            print(f'Grid resize outcome may be unknown. Inspect the sheet and backup {backup} before retrying.')
            raise
        if digest(fetch())!=proposal['snapshot_sha256']:
            raise SystemExit('Sheet values changed during grid expansion. No result values were written; replan and review.')
    try:
        response=service.values().batchUpdate(spreadsheetId=sid,body={'valueInputOption':'RAW','data':changes}).execute()
    except Exception:
        print(f'Write outcome may be unknown. Inspect the sheet and backup {backup} before retrying.')
        raise
    print(f"Wrote {response.get('totalUpdatedCells',0)} cells. Backup: {backup}")
    # Read back exact requested ranges; formatted values can differ for numeric cells.
    result=service.values().batchGet(spreadsheetId=sid,ranges=[item['range'] for item in changes],valueRenderOption='UNFORMATTED_VALUE').execute()
    for change,read in zip(changes,result['valueRanges']):
        expected_row=change['values'][0]; actual_row=(read.get('values') or [[]])[0]
        actual_row += ['']*(len(expected_row)-len(actual_row))
        if any(str(a)!=str(b) and not (isinstance(a,(int,float)) and isinstance(b,(int,float)) and a==b) for a,b in zip(expected_row,actual_row)):
            raise SystemExit(f"Verification mismatch at {change['range']}; inspect the sheet and backup before retrying.")
    print('Read-back verified. Replan before running again.')

if __name__=='__main__': main()
