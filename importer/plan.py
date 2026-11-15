"""Read-only validation and deterministic planning for racewalking imports."""
import argparse
import copy
import datetime
import difflib
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

HEADERS = {
    'Athletes': ['Athlete_ID','Name','Gender','YOB','Nationality','Prov','Note'],
    'Teams': ['Team_ID','Name','Aliases','Prov','Country'],
    'Races': ['Race_ID','Distance','Date','City','Prov','Country','Surface','Meet','Gender','Category','Timing','Notes'],
    'Results': ['Result_ID','Athlete_ID','Team_ID','Hour','Min','Sec','Race_ID','Rank'],
    'Splits': ['Result_ID','Distance','Hour','Min','Sec'],
}
IDS = {'Athletes':'Athlete_ID','Teams':'Team_ID','Races':'Race_ID','Results':'Result_ID'}
SPLITS = {Decimal(x) for x in ('1.5','3','5','10','15','20','21.1','30','35')}

def key(value):
    text = unicodedata.normalize('NFKD', str(value or '')).casefold()
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in text if not unicodedata.combining(c)).split())

def blank(value):
    return value is None or value == ''

def numeric(value):
    try:
        d = Decimal(str(value))
        if not d.is_finite(): raise ValueError()
        return d
    except (InvalidOperation, ValueError):
        raise ValueError('expected a finite number')

def mark(value):
    parts = str(value).strip().split(':')
    if len(parts) not in (2, 3): raise ValueError('time must be MM:SS or H:MM:SS')
    nums = [numeric(x) for x in parts]
    if any(x < 0 for x in nums) or nums[-1] >= 60 or (len(nums) == 3 and nums[-2] >= 60) or any(x != int(x) for x in nums[:-1]):
        raise ValueError('invalid time components')
    seconds = nums[-1] + nums[-2]*60 + (nums[0]*3600 if len(nums)==3 else 0)
    if seconds <= 0: raise ValueError('time must be positive')
    return seconds

def time_fields(seconds):
    return {'Hour':int(seconds // 3600), 'Min':int(seconds % 3600 // 60), 'Sec':float(seconds % 60)}

def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode()).hexdigest()

def audit(data):
    issues=[]
    for table, col in IDS.items():
        counts={}
        for row in data[table]: counts[str(row.get(col,''))]=counts.get(str(row.get(col,'')),0)+1
        for value,n in counts.items():
            if not value or n>1: issues.append(f'{table}: duplicate or missing {col} {value!r} ({n} rows)')
    for table, col, target, target_col in [('Results','Athlete_ID','Athletes','Athlete_ID'),('Results','Team_ID','Teams','Team_ID'),('Results','Race_ID','Races','Race_ID'),('Splits','Result_ID','Results','Result_ID')]:
        valid={str(r.get(target_col,'')) for r in data[target]}
        for i,row in enumerate(data[table],2):
            if str(row.get(col,'')) not in valid: issues.append(f'{table} row {i}: missing reference {col}={row.get(col)}')
    for table in ('Athletes','Teams'):
        rows=data[table]
        for i,a in enumerate(rows):
            for b in rows[i+1:]:
                ka,kb=key(a.get('Name')),key(b.get('Name'))
                if ka and kb and (ka==kb or (ka[0]==kb[0] and abs(len(ka)-len(kb))<=3 and min(len(ka),len(kb))>=5 and difflib.SequenceMatcher(None,ka,kb).ratio()>=.90)):
                    issues.append(f'{table}: possible duplicate IDs {a.get(IDS[table])} and {b.get(IDS[table])}')
    seen={}
    for i,row in enumerate(data['Results'],2):
        pair=(str(row.get('Athlete_ID')),str(row.get('Race_ID')))
        if pair in seen: issues.append(f'Results: possible duplicate athlete/race at rows {seen[pair]} and {i}')
        else: seen[pair]=i
    races={str(r.get('Race_ID')):r for r in data['Races']}
    for i,r in enumerate(data['Results'],2):
        try:
            dist=numeric(races[str(r['Race_ID'])]['Distance']); sec=numeric(r['Hour'])*3600+numeric(r['Min'])*60+numeric(r['Sec'])
            if sec > 0 and (sec/dist < 150 or sec/dist > 1800): issues.append(f'Results row {i}: unusual pace; review mark and distance')
        except (ValueError,KeyError,ZeroDivisionError): pass
    return issues

def plan(snapshot, incoming):
    data=copy.deepcopy(snapshot); operations=[]; errors=[]; created={}
    def err(msg): errors.append(msg)
    if 'races' in incoming:
        if 'results' in incoming: raise ValueError('Use either races or results, not both')
        flattened=[]
        for group in incoming['races']:
            for result in group.get('results',[]):
                if 'race' in result: raise ValueError('Place race details on the group, not individual results')
                flattened.append(dict(result, race=group.get('race')))
        incoming={k:v for k,v in incoming.items() if k!='races'}
        incoming['results']=flattened
    def entity(table, spec, label):
        if not isinstance(spec,dict): err(f'{label}: provide an object'); return None
        idcol=IDS[table]; rows=data[table]; name=spec.get('Name','')
        fields={k:v for k,v in spec.items() if k in HEADERS[table] and k != idcol and not blank(v)}
        ident=spec.get('id'); create=spec.get('create') is True
        if ident is not None:
            matches=[r for r in rows if str(r.get(idcol))==str(ident)]
            if len(matches)!=1: err(f'{label}: ID {ident} is missing or not unique'); return None
            row=matches[0]
        elif create:
            if table != 'Races' and not name: err(f'{label}: Name is required'); return None
            required = {'Athletes': ('Gender',), 'Races': ('Distance', 'Surface')}.get(table, ())
            missing = [field for field in required if blank(fields.get(field))]
            if table == 'Races' and key(fields.get('Country')) in ('can','canada') and blank(fields.get('Prov')):
                missing.append('Prov (province abbreviation for a Canadian race)')
            if missing: err(f'{label}: new record requires {", ".join(missing)}'); return None
            creation_key = (table, json.dumps(fields, sort_keys=True, ensure_ascii=False))
            if creation_key in created: return created[creation_key]
            if table == 'Races' and fields.get('Date') and fields.get('Distance'):
                candidates=[r for r in rows if str(r.get('Date',''))==str(fields['Date']) and str(r.get('Distance','')) in (str(fields['Distance']), str(float(fields['Distance']))) and (not fields.get('City') or not r.get('City') or key(r.get('City'))==key(fields['City'])) and (not fields.get('Gender') or not r.get('Gender') or key(fields['Gender'])==key(r['Gender']) or key(r['Gender'])=='mixed')]
                if candidates and spec.get('confirm_distinct') is not True: err(f'{label}: possible existing races {[r[idcol] for r in candidates]}; select an id or confirm_distinct=true after review'); return None
            # Creation is an explicit user decision, including if similar names exist.
            try: ident=max([int(r[idcol]) for r in rows]+[0])+1
            except (ValueError,TypeError,KeyError): err(f'{table}: non-numeric IDs prevent allocating a new ID'); return None
            row={h:'' for h in HEADERS[table]}; row[idcol]=ident; row.update(fields)
            rows.append(row); operations.append({'action':'append','table':table,'row':copy.deepcopy(row)}); created[creation_key]=ident
            return ident
        else:
            candidates=[]
            if table in ('Athletes','Teams') and name:
                for row in rows:
                    names=[row.get('Name','')]
                    if table=='Teams': names += re.split(r'[,;|]',str(row.get('Aliases','')))
                    if table=='Athletes':
                        aliases=re.findall(r'Previously listed as ([^.]+)\.',str(row.get('Note','')))
                        names += aliases
                    if key(name) and any(key(name)==key(n) for n in names): candidates.append(row)
                if len(candidates)==1:
                    row=candidates[0]
                else:
                    similar=[f"{r[idcol]}: {r.get('Name')}" for r in rows if key(name) and difflib.SequenceMatcher(None,key(name),key(r.get('Name'))).ratio()>=.75]
                    err(f'{label}: choose id or explicitly set create=true; candidates: {similar[:10]}'); return None
            else:
                err(f'{label}: choose an existing id or explicitly set create=true'); return None
        ident=row[idcol]
        changes={}
        if spec.get('add_aliases'):
            if table != 'Teams' or not isinstance(spec['add_aliases'],list):
                err(f'{label}: add_aliases must be a list for a team'); return None
            aliases=[x.strip() for x in re.split(r'[,;|]',str(row.get('Aliases',''))) if x.strip()]
            for alias in spec['add_aliases']:
                if not isinstance(alias,str) or not alias.strip() or re.search(r'[,;|]',alias):
                    err(f'{label}: invalid alias'); continue
                if key(alias) not in [key(x) for x in aliases] and key(alias)!=key(row.get('Name')): aliases.append(alias.strip())
            if ', '.join(aliases)!=str(row.get('Aliases','')) and aliases: changes['Aliases']=', '.join(aliases)
        corrections=spec.get('corrections', {})
        if not isinstance(corrections,dict): err(f'{label}: corrections must be an object'); return None
        for col,change in corrections.items():
            if col not in HEADERS[table] or col==idcol or not isinstance(change,dict) or 'from' not in change or 'to' not in change:
                err(f'{label}: invalid correction for {col}'); continue
            if str(row.get(col,''))!=str(change['from']):
                err(f'{label}: correction for {col} no longer matches the existing value'); continue
            changes[col]=change['to']
        for col,val in fields.items():
            if col=='Name' and key(row.get(col))==key(val): continue
            if col=='Name' and table=='Teams' and key(val) in [key(n) for n in re.split(r'[,;|]',str(row.get('Aliases','')))]: continue
            if col=='Name' and table=='Athletes' and key(val) in [key(n) for n in re.findall(r'Previously listed as ([^.]+)\.',str(row.get('Note','')))]: continue
            if blank(row.get(col)): changes[col]=val
            elif str(row[col]).strip()!=str(val).strip():
                err(f'{label}: {col} conflicts with existing ID {ident}; resolve before import')
        if changes:
            row.update(changes); operations.append({'action':'update','table':table,'id':ident,'fields':changes})
        return ident
    for index, update in enumerate(incoming.get('updates',[]),1):
        table=update.get('table') if isinstance(update,dict) else None
        if table not in ('Athletes','Teams','Races','Results'): err(f'update {index}: invalid table'); continue
        entity(table,update.get('record'),f'update {index} {table}')
    for index,item in enumerate(incoming.get('results',[]),1):
        label=f'result {index}'
        if not isinstance(item,dict): err(f'{label}: expected object'); continue
        aid=entity('Athletes',item.get('athlete'),label+' athlete')
        tid=entity('Teams',item.get('team'),label+' team')
        rid=entity('Races',item.get('race'),label+' race')
        if None in (aid,tid,rid): continue
        rank=item.get('rank',''); raw=item.get('time'); status=str(rank).upper()
        if blank(raw) and status not in ('DQ','DNF','NT') and item.get('no_time') is not True: err(f'{label}: provide time, DQ/DNF/NT, or explicitly set no_time=true'); continue
        try:
            seconds=mark(raw) if not blank(raw) else Decimal(0)
            race=next(r for r in data['Races'] if str(r['Race_ID'])==str(rid)); distance=numeric(race['Distance'])
            if distance<=0: raise ValueError('distance must be positive')
        except (ValueError, KeyError) as ex: err(f'{label}: {ex}'); continue
        if seconds and (seconds/distance<150 or seconds/distance>1800) and item.get('confirm_unusual_time') is not True:
            err(f'{label}: unusual pace; confirm the mark with confirm_unusual_time=true'); continue
        existing=[r for r in data['Results'] if str(r.get('Athlete_ID'))==str(aid) and str(r.get('Race_ID'))==str(rid)]
        if len(existing)>1: err(f'{label}: multiple results for athlete/race; resolve duplicate first'); continue
        if existing:
            result=existing[0]; resultid=result['Result_ID']
            if sum(str(r.get('Result_ID'))==str(resultid) for r in data['Results'])!=1: err(f'{label}: result ID is not unique'); continue
            actual=sum(numeric(result.get(k,0) or 0)*factor for k,factor in [('Hour',3600),('Min',60),('Sec',1)])
            if actual != seconds or str(result.get('Rank','')).casefold()!=str(rank).casefold() or str(result.get('Team_ID'))!=str(tid):
                err(f'{label}: existing result conflicts; review manually'); continue
        else:
            # Identical marks can be published with conflicting dates or venue names.
            # Compare across race IDs before appending, including races created earlier
            # in this same plan. DQ/DNF and zero-time sentinels are not comparable.
            possible=[]
            if seconds:
                try: current_date=datetime.date.fromisoformat(str(race.get('Date','')))
                except ValueError: current_date=None
                if current_date:
                    race_by_id={str(r['Race_ID']):r for r in data['Races']}
                    for candidate in data['Results']:
                        if str(candidate.get('Athlete_ID'))!=str(aid) or str(candidate.get('Race_ID'))==str(rid): continue
                        other=race_by_id.get(str(candidate.get('Race_ID')), {})
                        try:
                            delta=abs((current_date-datetime.date.fromisoformat(str(other.get('Date','')))).days)
                            other_time=sum(numeric(candidate.get(k,0) or 0)*f for k,f in [('Hour',3600),('Min',60),('Sec',1)])
                            if delta<=31 and numeric(other.get('Distance'))==distance and other_time==seconds:
                                possible.append(candidate['Result_ID'])
                        except (ValueError, TypeError): continue
            if possible and item.get('confirm_distinct_result') is not True:
                err(f'{label}: possible duplicate results {possible} with identical athlete, distance and mark within 31 days; review before confirming a distinct result'); continue
            try: resultid=max([int(r['Result_ID']) for r in data['Results']]+[0])+1
            except (ValueError,KeyError): err('Results: cannot allocate ID'); continue
            result={'Result_ID':resultid,'Athlete_ID':aid,'Team_ID':tid,'Race_ID':rid,'Rank':rank,**time_fields(seconds)}
            data['Results'].append(result); operations.append({'action':'append','table':'Results','row':result})
        for split in item.get('splits',[]):
            try:
                d=numeric(split['distance']); s=mark(split['time'])
                if d not in SPLITS: raise ValueError('distance is not a supported split')
                if d>=distance: raise ValueError('split distance must be shorter than race')
                if seconds and s>=seconds: raise ValueError('split must be faster than final time')
                if (s/d<150 or s/d>1800) and split.get('confirm_unusual_time') is not True: raise ValueError('unusual split pace; confirm with confirm_unusual_time=true')
                found=[r for r in data['Splits'] if str(r.get('Result_ID'))==str(resultid) and numeric(r.get('Distance'))==d]
                if found:
                    if len(found)!=1 or sum(numeric(found[0].get(k,0) or 0)*f for k,f in [('Hour',3600),('Min',60),('Sec',1)])!=s: raise ValueError('split conflicts with existing split')
                else:
                    row={'Result_ID':resultid,'Distance':float(d),**time_fields(s)}; data['Splits'].append(row); operations.append({'action':'append','table':'Splits','row':row})
            except (KeyError,ValueError,TypeError) as ex: err(f'{label} split: {ex}')
    if not incoming.get('results') and not incoming.get('updates'): err('Provide at least one result or update')
    return {'snapshot_sha256':digest(snapshot),'source':incoming.get('source',''),'input':incoming,'errors':errors,'audit':audit(snapshot),'operations':operations}

def fetch():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    directory=Path('secrets'); paths=list(directory.glob('*.json'))
    if len(paths)!=1: raise ValueError('secrets/ must contain exactly one service-account JSON file')
    creds=Credentials.from_service_account_file(str(paths[0]),scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
    service=build('sheets','v4',credentials=creds).spreadsheets(); sid=(directory/'sheet_id.txt').read_text().strip()
    data={}
    for table,headers in HEADERS.items():
        values=service.values().get(spreadsheetId=sid,range="'"+table+"'",valueRenderOption='FORMATTED_VALUE').execute().get('values',[])
        if not values or values[0]!=headers: raise ValueError(f'{table}: unexpected headers; inspect workbook before proceeding')
        data[table]=[dict(zip(headers,row+['']*(len(headers)-len(row)))) for row in values[1:]]
    return data

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path); parser.add_argument('--snapshot',type=Path,help='use saved JSON snapshot instead of Sheets'); parser.add_argument('--output',type=Path,default=Path('import-plan.json'))
    args=parser.parse_args()
    try:
        snapshot=json.loads(args.snapshot.read_text(encoding='utf-8-sig')) if args.snapshot else fetch()
        proposal=plan(snapshot,json.loads(args.input.read_text(encoding='utf-8-sig')))
        args.output.write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(f"Plan written to {args.output}: {len(proposal['operations'])} proposed operations, {len(proposal['errors'])} questions/errors, {len(proposal['audit'])} existing warnings. No Sheets data was changed.")
        return 1 if proposal['errors'] else 0
    except (OSError,ValueError,KeyError,json.JSONDecodeError) as ex:
        parser.exit(2,f'Error: {ex}\n')
if __name__=='__main__': raise SystemExit(main())
