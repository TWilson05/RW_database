# Canadian Racewalk Database: project context

This document is a planning reference for future chats. It records the project's goals and current state; proposed design choices and open questions are not yet implementation decisions.

## Goal and near-term priority

Build a continuously updated database of Canadian racewalking results and rankings, eventually presented through a web dashboard. It should preserve historical results as well as current performances, even when source information is incomplete.

The existing ingestion workflow lets an agent find and interpret results from sources, then plan and apply reviewed changes to Google Sheets. The user can supply sources or request a search of a particular website. See [HANDOFF.md](HANDOFF.md) for coverage, priorities, and the next-session checklist; recheck the live sheet before writing.

## Existing project

- `app.py` is a Streamlit dashboard that reads Google Sheets through `gspread` and service-account credentials from Streamlit secrets. It reads worksheets named `Athletes`, `Races`, `Results`, `Teams`, and optionally `Splits`.
- The app currently expects athlete IDs, names, gender, year of birth and nationality; race IDs, distance, date, city, province, country and surface; result and team IDs; and split records linked by result ID. The inspected sheet schema and known data issues are recorded below; recheck the live sheet before making changes.
- `2025_lookup_table.json` supplies the app's current World Athletics scoring lookup. `requirements.txt` lists the Python dependencies.
- The existing app provides leaderboards and athlete profiles, but these are not yet the full desired behavior. In particular, its shared data preparation excludes DQ and DNF results from profiles as well as rankings, and identifies personal bests and profiles by name rather than athlete ID. It also excludes splits from DQ/DNF results; the desired policy for those splits needs clarification. Treat existing behavior as implementation, not as a definitive business rule.

## Working with the repository and data

The dashboard opens the `Canadian Racewalk` spreadsheet using `gspread` and Streamlit's `gcp_service_account` secrets. Local service-account credentials and the spreadsheet ID are in the ignored `secrets/` directory; do not commit or print credential contents. The Sheets API can be accessed read-only with the service-account JSON and ID there. The dashboard caches data for 10 minutes. For local setup, install `requirements.txt`, configure Streamlit secrets, and run `streamlit run app.py`.

`importer/plan.py` and `importer/apply.py` support agent-reviewed imports, documented in `importer/README.md`. Input can contain results grouped by race; the agent interprets sources, reviews matches, asks the user when uncertain, and applies a reviewed plan. Matching and audit checks are heuristic. Confirmed former athlete names can be persisted in `Note` using the limited `Previously listed as NAME.` convention recognized by the planner; team aliases are stored in `Aliases`. The Sheets writer does not lock against concurrent edits.

## Google Sheets structure

The workbook was inspected read-only on 2026-11-14. The tables below describe its actual headers; column and worksheet names are case-sensitive in the app. Counts and data-quality findings are a snapshot and will change as the sheet is updated.

The app opens the spreadsheet named `Canadian Racewalk` using a Google service account configured as `gcp_service_account` in Streamlit secrets. It reads these worksheets with the first row as headers:

| Worksheet | Columns in sheet (in order) | Purpose |
| --- | --- | --- |
| `Athletes` | `Athlete_ID`, `Name`, `Gender`, `YOB`, `Nationality`, `Prov`, `Note` | Athlete identity and attributes; `YOB` is year of birth. |
| `Races` | `Race_ID`, `Distance`, `Date`, `City`, `Prov`, `Country`, `Surface`, `Meet`, `Gender`, `Category`, `Timing`, `Notes` | Race distance, date, location, surface and event details; `Prov` is province or state. |
| `Results` | `Result_ID`, `Athlete_ID`, `Team_ID`, `Hour`, `Min`, `Sec`, `Race_ID`, `Rank` | An athlete's placing or status and time in a race, plus their team. |
| `Teams` | `Team_ID`, `Name`, `Aliases`, `Prov`, `Country` | Team identity, alternate names and location. |
| `Splits` | `Result_ID`, `Distance`, `Hour`, `Min`, `Sec` | Intermediate performances associated with a result. This worksheet is optional in the current app. |

The app reads only a subset of these columns: it currently ignores athlete `Prov` and `Note`, race `Meet`, `Gender`, `Category`, `Timing` and `Notes`, and team `Aliases`, `Prov` and `Country`.

### Relationships and conventions

- `Results.Athlete_ID` links to `Athletes.Athlete_ID`; `Results.Race_ID` links to `Races.Race_ID`; and `Results.Team_ID` links to `Teams.Team_ID`. An unmatched team is displayed as `Unattached`. Team ID `0` is an existing team record, so it must not automatically be treated as a missing foreign key. ID-generation rules remain to be established.
- `Splits.Result_ID` links to `Results.Result_ID`. A split inherits its athlete, race and team from that result and uses its own distance and time. The dashboard appends `+` to the displayed split mark.
- Distances are treated as numeric kilometres (for example, `1.5` for 1500 m and `20` for 20 km). The current dashboard only displays a fixed set of distances: 1.5, 1.609, 3, 5, 10, 15, 20, 21.1, 30, 35, 42.2 and 50 km.
- Time is assembled in seconds from `Hour`, `Min` and `Sec`; seconds can be fractional. Road marks are rounded up to whole seconds for display; other surfaces are displayed to hundredths. Most race dates are stored as Sheets date values; some are text, including a year-only value. Preserve partial dates rather than fabricating a full date.
- Observed athlete genders are `Male` and `Female`; race genders include `Mixed`, `Men`, `Women` and `Female`. Race surfaces are `Road`, `Track` and `Indoor`. Race categories include `Open`, age groups and other competition labels. `Timing` includes `h`, `NJ` and `Electric`; their intended meanings have not been verified.
- `Rank` can be a number, blank or text such as `DQ`, `DNF`, `NT` or `1Q`. Treat it as a reported value rather than assuming it is always numeric. Several fields, including year of birth, meet, location and team information, can be blank.
- The dashboard filters for `Nationality` equal to `CAN` (case-insensitive). It excludes results with `Rank` of `DQ`, `DNF` or `NT` from its main data; splits from `DQ` and `DNF` are excluded, while splits from `NT` can be included. This currently affects athlete profiles too, although the project goal is to show DQ and DNF in result views.
- Athlete profiles and personal-best identification currently use `Name`, not `Athlete_ID`. The planned ingestion system must not assume names are unique.

### Data-quality snapshot

At inspection, the sheet had 2,147 results, 621 athletes, 833 races, 176 teams and 324 splits. Athlete, race and team IDs were individually unique, but result ID `845` occurred twice. All result athlete and race references matched existing IDs; one result referenced missing team ID `75`, and one split referenced missing result ID `1681`. No duplicate `(Result_ID, Distance)` split pairs were observed. These findings need investigation before automated writes; do not silently repair or merge records based on this snapshot. The dashboard's join on a duplicated result ID can also multiply associated split rows.

## World Athletics scoring implementation

The dashboard uses `2025_lookup_table.json` to calculate points from gender, distance, surface and elapsed time; it returns zero when no applicable lookup is found. Review scoring behavior and eligibility before treating this as authoritative for ingestion or historical records.

## Information to represent

- **Athlete:** a stable unique identity, display name, year of birth, gender, country of affiliation, and optional province. One athlete can have many results. Names can have aliases, abbreviations, variants and typos; names alone are not unique identifiers.
- **Competition and race:** competition name, date, location, province or state where applicable, and country. A race should be uniquely identifiable and connect to many athletes' results so its results can be reconstructed. Record distance, surface (road, track or indoor), and race gender/category (men, women or mixed) at the appropriate level. A competition may contain multiple races; the precise competition/race distinction and sheet mapping need design.
- **Result:** link an athlete to a race, including placement, time or status, and the team represented for that result. Distance may come from the race or be recorded on the result when necessary. Preserve DQ and DNF in athlete and race views, but exclude them from rankings.
- **Team:** an identifier, name and province where known. Team standardization is a lower priority, and affiliation may change over time.
- **Split:** an intermediate distance and elapsed time linked to its parent result, not a separate race, competition or result. Eligible splits can appear in rankings with `+` after the time; retain the connection to the original performance.
- **Source and provenance:** retain source references and enough original text or values to trace and review interpretations, conflicting reports, updates and duplicate decisions. Multiple sources can describe the same performance.

Canadian affiliation can usually be assumed when supported by context, such as a Canadian national championship. Use competition year, reported two-digit years, age or school grade to infer a plausible birth year when the context supports it; document the inference and ask the user if the evidence remains uncertain. Do not present an inferred exact year as known when an age or grade permits multiple years. When a source states a birth year directly rather than an estimate inferred from age or grade, prefer the directly stated year and replace a small difference in the inferred value; retain the source and reasoning. If provenance or conflicting direct reports make the better value unclear, ask the user.

Missing data is normal, especially for older records: do not invent birth years, full dates or other facts. Preserve the precision actually known (for example, a year without a day) and distinguish unknown values from guesses. Preserve raw reported marks and source details alongside normalized values where useful.

## Display and ranking requirements

- Show all races for an athlete and reconstruct the results of a race. Use stable IDs for joins and identity-sensitive views.
- Support sorting or filtering performances by World Athletics points, time, distance and year, with views of all performances or the best performance per athlete. Define the grouping for “best” explicitly, especially across distances and surfaces.
- Link performances to applicable World Athletics points. Record or otherwise make clear the scoring table/version and rules used; an unavailable or inapplicable score should not be confused with a valid score. Confirm eligibility and scoring rules rather than assuming every distance, split or historical mark is scoreable.
- Road times are generally reported to the second; track and indoor times to the hundredth. Record the reported precision and surface when known. Precision can suggest a surface, but inference is not proof and exceptions should remain reviewable.
- DQ and DNF must remain visible in results but not appear in rankings. The treatment of intermediate splits from a DQ or DNF requires a decision.

## Sources and ingestion principles

Modern results often come from Athletics Canada rankings or World Athletics rankings; historical material may come from official results, re-reports or irregularly formatted text. Sources may be incomplete, inconsistent or duplicate one another. Respect source access restrictions and verify any extracted information against its source.

When sources conflict on results, prefer official results over summaries and rankings where available; otherwise choose the best-supported source, with extra reported precision a useful but not conclusive clue. For names, prefer Canadian sources, especially Quebec sources for francophone athletes. World Athletics and Athletics Canada integrated databases are strong references, but an original official result can correct a transcription in a later ranking. For a minor discrepancy choose a provisional value, record competing values, sources, and why it needs verification, rather than omitting the result. Do not treat an unconfirmed spelling as a confirmed identity alias. Ask when an uncertain identity match or substantive ambiguity risks merging different people or races. Other sources can supply additional context and performances. The user's separate convention for small race-date discrepancies (use the later date) still applies. Rachel Seaman, born in 1986, previously competed as Rachel Lavallée; these names refer to one athlete.

A useful workflow should discover or accept source material, retain its reference, extract structured candidates, normalize dates, distances, marks and statuses without discarding their original form, validate links and missing fields, and compare candidates against existing athletes, races, results and splits. It should produce a reviewable plan of additions, updates, likely duplicates and conflicts before applying changes. Record minor unresolved source conflicts and import a clearly identified provisional value, following the source preference above. Surface uncertain identity matches and substantive ambiguity for a decision rather than silently merging or inventing facts.

Duplicate detection should use multiple independent clues where available: source identifiers, name variants and aliases, birth year, affiliation, dates, location, distance, marks and competition details. For example, Ben and Benjamin may be the same athlete, but a nickname or similar mark alone is not proof. Handle duplicate sources separately from duplicate entities and performances, preserve provenance when consolidating, and make changes auditable and recoverable. Reprocessing the same source should not create duplicate records. Use stable IDs and avoid destructive overwrites when evidence is uncertain.

The current workflow, safeguards, backup strategy, and their limitations are described in [importer/README.md](importer/README.md); confidence thresholds and a structured provenance store remain open design work. Avoid storing credentials in the repository or this document.

## Open questions for planning

1. What ID-generation conventions should be used, and how should proposed fields map to the existing sheet without breaking the dashboard?
2. What distinguishes a competition from an individual race, including multiple categories or heats at one meet?
3. Which splits qualify for rankings, especially when the parent result is DQ or DNF? Which World Athletics scoring version and eligibility rules should apply?
4. What constitutes a best performance per athlete when distances, surfaces, categories or years differ? How should ties be displayed?
5. How should incomplete dates, uncertain identities, conflicting source claims and corrections be reviewed and recorded? Which changes may be automatic?
6. What is the desired scope for Canadian affiliation over time, and how should historical changes in country, team or athlete details be represented?

## Meet date convention

When the day of a race at a multi-day meet is unknown, use the final day of the meet as an assumed date, following Athletics Canada rankings, and record that it is an assumption. When plausible reports of the same race differ by one or a few days, use the later date, including when the reports come from Athletics Canada and World Athletics. Confirm the athlete and race match first, and retain the conflicting source information; do not apply this rule to potentially separate races or larger unexplained differences.

The user generally does not require retaining annotations such as X, >, ~ or meet records. For international competitions, import only Canadian athletes' results unless full fields are explicitly requested, and generally limit stored splits to Canadian athletes at relevant ranking distances. Ignore DNS and relay events. Include the 1906 Intercalated Games when reviewing historical Olympic-related results.

When existing data conflicts with official results, prefer the official source; the original data may contain transcription errors. Preserve fractional road times when reported, leaving display rounding to the dashboard. Keep source details and verify the actual event and athlete before correcting an existing row.
