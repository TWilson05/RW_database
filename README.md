# Canadian Racewalk Database

A database and dashboard for exploring Canadian racewalking performances, from historical results to recent races. The project aims to make athlete results and rankings easier to find, compare and maintain.

**Website:** [Canadian Racewalk Database](https://canadian-racewalk-database.streamlit.app/)

The current dashboard offers leaderboards and athlete profiles, with filtering by distance, gender and year and sorting by time or World Athletics points. It draws results from a Google Sheets workbook and uses a local World Athletics scoring lookup. Automated ingestion of new results and duplicate handling are planned.

## Project structure

- [app.py](app.py) ? Streamlit dashboard and Google Sheets data loading.
- [2025_lookup_table.json](2025_lookup_table.json) ? scoring lookup used by the dashboard.
- [requirements.txt](requirements.txt) ? Python dependencies.
- [context.md](context.md) ? working context, sheet schema, data conventions, known issues and planning decisions.

The workbook is organized into `Athletes`, `Races`, `Results`, `Teams` and `Splits` worksheets. Results connect athletes to races and teams; splits connect to their parent results.

## Run locally

Install the dependencies with `pip install -r requirements.txt`, configure Streamlit's `gcp_service_account` secrets with access to the workbook, and run `streamlit run app.py`. Keep credentials out of the repository.
