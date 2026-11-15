# Agent-assisted imports

The agent converts source material into structured JSON, researches or checks uncertain identities, reviews the planner's output with the user where needed, and applies the reviewed plan. Results may be grouped under multiple races. The scripts do not perform web searches or infer birth years themselves: the agent provides those interpretations, with source and reasoning, and asks the user when uncertainty remains.

Install the project dependencies. Place the service-account JSON and `sheet_id.txt` in the ignored `secrets/` directory. From the repository root:

```sh
python importer/plan.py path/to/input.json --output path/to/plan.json
python importer/apply.py path/to/plan.json
```

For a separate read-only check before planning, run `python importer/check_duplicates.py path/to/input.json --output path/to/duplicate-report.json`. It reports matching athlete/race results within two days of the supplied date, including differing dates, marks and placements. It also flags an identical athlete, distance and mark within 31 days across different races, even with a different city. The planner blocks the latter until the agent verifies the performances; use `confirm_distinct_result: true` only after establishing they are separate races. Checks use exact IDs or normalized names; absence from the report does not prove a result is new, and aliases, partial dates and alternate locations still require review.

Review the plan's `errors`, `audit`, and `operations` before applying it. Resolve errors by updating the input and replanning. The apply command re-reads the workbook and refuses a stale or altered plan, saves a backup and the input under `secrets/import-backups/`, expands worksheet rows when necessary, sends a single batch of changes, and reads them back. If a write fails or its outcome is uncertain, inspect the sheet and backup before retrying. The snapshot checks do not provide a transactional lock: avoid concurrent edits while applying. Keep plans and backups private when their contents are sensitive.

Use `races`, an array of objects with a `race` object and `results` array. Each result supplies `athlete`, `team`, `rank`, `time` and optional `splits`; see [the example](../examples/import.json). Use `id` for a confirmed existing entity or `create: true` and sheet column names for an explicitly confirmed new one. The planner flags potential existing races with the same date, distance and city before creating one, even when their categories differ. After confirming that a candidate is a separate race, use `confirm_distinct: true` with `create: true`; incomplete dates, alternate formats and locations can still hide duplicates, so the agent must search candidates and resolve uncertainty. Athlete and team names match without accent differences, and existing team aliases are checked. Similar names and multiple candidates need review. For athlete records, names saved in `Note` as `Previously listed as NAME.` are also recognized as confirmed former names; this limited convention is not a general alias registry.

Times use `MM:SS` or `H:MM:SS`; `rank` may contain `DQ`, `DNF` or `NT` without a time. Splits use `distance` in kilometres and `time`; use `21.1` for the sheet's half-marathon convention. Road/track precision should follow the source. The planner flags unusual paces for review; once verified, set `confirm_unusual_time: true` on the result or split. Team ID `0` is an existing record, not a missing value.

When a finisher's placing is known but their time is unavailable, supply the numeric `rank` and `no_time: true`. The sheet stores zero in the time components as a sentinel; the current dashboard excludes that result because it requires a positive time.

Supply all known data and keep unknown values blank. New athletes require `Name` and `Gender`; the current dashboard filters out athletes without nationality `CAN`. New teams require `Name`, and new races require `Distance` and `Surface`. For Canadian races supply the province abbreviation, researching the location if the source omits it; the planner requires it for new Canadian races. The planner can fill empty existing fields, but reports conflicting nonblank values. A general structured athlete alias and source store is still needed.

The audit flags duplicate IDs, broken references, similar athlete/team names, repeated athlete/race pairs and extreme paces. Its heuristics can miss issues or produce false positives. Existing warnings do not automatically block imports; review them and do not silently repair them. The planner does not validate every split ordering, source claim or scoring eligibility. `--snapshot path/to/snapshot.json` supports offline planning. Exit status 1 indicates unresolved input errors and 2 indicates read or input failure. The old flat `results` format remains supported.

For an explicitly confirmed correction to an existing nonblank field, provide `corrections`, for example `{"Name": {"from": "Old Name", "to": "Correct Name"}}` in the entity object with its `id`. The plan rejects the correction if the current value differs. The agent should retain the former name using the confirmed-name convention above when appropriate. The writer stores IDs as numeric values on new rows.

To merge confirmed duplicate athletes after reviewing their fields and race results, run `python importer/merge_athletes.py SOURCE_ID TARGET_ID`. It refuses conflicting or unpreserved source fields and same-race results, backs up the snapshot, transfers result links, deletes the source athlete row, and verifies the merge. Avoid concurrent sheet edits during the operation.

For metadata without a race, use an `updates` array instead of `races`:

```json
{
  "source": "Source or user confirmation",
  "updates": [
    {"table": "Teams", "record": {"id": 173, "add_aliases": ["Australia Sports"]}},
    {"table": "Athletes", "record": {"id": 234, "corrections": {"YOB": {"from": "1999", "to": 1998}}}}
  ]
}
```

Run the same plan and apply commands. `add_aliases` preserves existing team aliases and avoids normalized duplicates. Use ordinary fields for filling blanks, and a `from`/`to` correction for a confirmed replacement. Race annotations such as X, >, ~ and meet records generally need not be retained.

To merge confirmed duplicate results, use `python importer/merge_duplicate_results.py SOURCE_ID TARGET_ID`. It checks athlete, race, team and placement, allows marks that differ only by whole-second rounding, and refuses to delete a source result that has splits. Choose the better-sourced target mark before merging. The command saves a backup and verifies the deletion.
