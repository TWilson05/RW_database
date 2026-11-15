"""Find likely duplicate races and results in a grouped import without writing."""
import argparse
import datetime
import json
from pathlib import Path
from plan import fetch, key, mark, numeric


def compare(snapshot, incoming, date_window=2):
    findings=[]
    athletes={str(a['Athlete_ID']):a for a in snapshot['Athletes']}
    for group in incoming.get('races',[]):
        spec=group.get('race',{}); candidates=[]
        for race in snapshot['Races']:
            if 'id' in spec:
                if str(race.get('Race_ID'))!=str(spec['id']): continue
            else:
                try:
                    if numeric(race.get('Distance'))!=numeric(spec['Distance']): continue
                    delta=abs((datetime.date.fromisoformat(str(race['Date']))-datetime.date.fromisoformat(str(spec['Date']))).days)
                except (KeyError,ValueError,TypeError): continue
                if delta>date_window: continue
                if spec.get('City') and race.get('City') and key(spec['City'])!=key(race['City']): continue
                if any(spec.get(field) and race.get(field) and key(spec[field])!=key(race[field]) for field in ('Gender','Category')): continue
            candidates.append(race)
        for race in candidates:
            for entry in group.get('results',[]):
                a=entry.get('athlete',{}); aid=str(a['id']) if 'id' in a else None
                ids=[aid] if aid else [i for i,v in athletes.items() if key(v.get('Name'))==key(a.get('Name')) and key(a.get('Name'))]
                for result in snapshot['Results']:
                    if str(result.get('Race_ID'))!=str(race.get('Race_ID')) or str(result.get('Athlete_ID')) not in ids: continue
                    try:
                        existing=sum(numeric(result.get(f,0) or 0)*n for f,n in [('Hour',3600),('Min',60),('Sec',1)])
                        submitted=mark(entry['time']) if entry.get('time') else 0
                        same_time=existing==submitted
                    except ValueError: same_time=False
                    findings.append({'race_id':race['Race_ID'],'race_date':race.get('Date'),'input_date':spec.get('Date'),'result_id':result.get('Result_ID'),'athlete_id':result.get('Athlete_ID'),'athlete':athletes.get(str(result.get('Athlete_ID')),{}).get('Name'),'same_mark':same_time,'same_rank':str(result.get('Rank','')).casefold()==str(entry.get('rank','')).casefold()})
        # A source may report the same performance under a different date, city,
        # or category. Search exact marks across race IDs independently of the
        # narrower race-matching rules above.
        if 'id' in spec:
            source_race=next((r for r in snapshot['Races'] if str(r.get('Race_ID'))==str(spec['id'])), {})
        else: source_race=spec
        try:
            source_date=datetime.date.fromisoformat(str(source_race['Date']))
            distance=numeric(source_race['Distance'])
        except (KeyError,ValueError,TypeError): continue
        races={str(r['Race_ID']):r for r in snapshot['Races']}
        for entry in group.get('results',[]):
            a=entry.get('athlete',{}); aid=str(a['id']) if 'id' in a else None
            ids=[aid] if aid else [i for i,v in athletes.items() if key(v.get('Name'))==key(a.get('Name')) and key(a.get('Name'))]
            try: submitted=mark(entry['time'])
            except (KeyError,ValueError,TypeError): continue
            if not submitted: continue
            for result in snapshot['Results']:
                if str(result.get('Athlete_ID')) not in ids or any(str(f['result_id'])==str(result.get('Result_ID')) for f in findings): continue
                race=races.get(str(result.get('Race_ID')), {})
                try:
                    delta=abs((source_date-datetime.date.fromisoformat(str(race['Date']))).days)
                    existing=sum(numeric(result.get(f,0) or 0)*n for f,n in [('Hour',3600),('Min',60),('Sec',1)])
                    if delta>31 or numeric(race['Distance'])!=distance or existing!=submitted: continue
                except (KeyError,ValueError,TypeError): continue
                findings.append({'race_id':race['Race_ID'],'race_date':race.get('Date'),'input_date':source_race.get('Date'),'result_id':result.get('Result_ID'),'athlete_id':result.get('Athlete_ID'),'athlete':athletes.get(str(result.get('Athlete_ID')),{}).get('Name'),'same_mark':True,'same_rank':str(result.get('Rank','')).casefold()==str(entry.get('rank','')).casefold(),'reason':'same athlete, distance and mark within 31 days'})
    return findings


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('input',type=Path); parser.add_argument('--snapshot',type=Path); parser.add_argument('--output',type=Path,default=Path('duplicate-report.json')); args=parser.parse_args()
    s=json.loads(args.snapshot.read_text(encoding='utf-8-sig')) if args.snapshot else fetch()
    results=compare(s,json.loads(args.input.read_text(encoding='utf-8-sig')))
    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{len(results)} possible existing results; inspect {args.output}. No sheet changes.')

if __name__=='__main__': main()
