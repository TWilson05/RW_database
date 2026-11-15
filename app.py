import streamlit as st
import pandas as pd
import gspread
import math
import json
import bisect
from google.oauth2.service_account import Credentials

# 1. Page Config
st.set_page_config(page_title="Canadian Racewalk Database", layout="wide")

# 2. Secure Google Sheets Connection
@st.cache_resource
def get_gspread_client():
    credentials_dict = st.secrets["gcp_service_account"]
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
    return gspread.authorize(creds)

# Helper function to map distances to clean strings
def format_distance_string(d):
    try:
        d_float = float(d)
    except ValueError:
        return str(d)
    
    if d_float == 0.8: return "800m"
    if d_float == 1.5: return "1500m"
    if math.isclose(d_float, 1.609, rel_tol=1e-4): return "Mile"
    if d_float == 21.1: return "Half Marathon"
    if d_float == 42.2: return "Marathon"
    if d_float.is_integer(): return f"{int(d_float)}km"
    return f"{d_float}km"

# Load World Athletics JSON Data
@st.cache_data
def load_wa_table():
    try:
        with open('2025_lookup_table.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# Calculate WA Points
def calculate_wa_points(gender, dist_num, surface, seconds, wa_table):
    try:
        dist_float = float(dist_num)
    except ValueError:
        return 0
        
    if dist_float < 3:
        return 0
        
    g_key = "Men" if str(gender).strip().lower() in ['male', 'm', 'men'] else "Women"
    
    if g_key not in wa_table:
        return 0
        
    surf = str(surface).strip().title()
    
    # Force 21.1km (Half Marathon) to use Road Table logic even if run on a Track
    is_road = (surf == 'Road') or math.isclose(dist_float, 21.1, abs_tol=0.01)
    
    scoring_seconds = math.ceil(seconds) if is_road else seconds

    possible_keys = []
    
    if is_road:
        if int(dist_float * 10) == 211:
            possible_keys = ["HMW", "HMW ", "Half Marathon W"]
        elif int(dist_float * 10) == 422:
            possible_keys = ["MarW", "MarW ", "Marathon W"]
        else:
            base = int(dist_float) if dist_float.is_integer() else dist_float
            possible_keys = [
                f"{base}km W", f"{base}kmW", f"{base} km W"
            ]
    else:
        meters = int(dist_float * 1000)
        if meters >= 10000:
            possible_keys = [f"{meters:,}mW", f"{meters}mW"]
        else:
            possible_keys = [f"{meters}mW", f"{meters:,}mW"]
            
    thresholds = None
    for pk in possible_keys:
        if pk in wa_table[g_key]:
            thresholds = wa_table[g_key][pk]
            break
            
    if not thresholds:
        return 0

    idx = bisect.bisect_left(thresholds, scoring_seconds)
    
    if idx < len(thresholds):
        points = 1400 - idx
        return max(0, points)
        
    return 0

# 3. Load, Merge, and Clean Data
@st.cache_data(ttl=600)
def load_data():
    gc = get_gspread_client()
    sh = gc.open("Canadian Racewalk")
    wa_table = load_wa_table()

    # Load raw tables
    df_athletes_raw = pd.DataFrame(sh.worksheet('Athletes').get_all_records())
    df_races_raw = pd.DataFrame(sh.worksheet('Races').get_all_records())
    df_results = pd.DataFrame(sh.worksheet('Results').get_all_records())
    df_teams_raw = pd.DataFrame(sh.worksheet('Teams').get_all_records())
    
    try:
        df_splits = pd.DataFrame(sh.worksheet('Splits').get_all_records())
    except gspread.exceptions.WorksheetNotFound:
        df_splits = pd.DataFrame(columns=['Result_ID', 'Distance', 'Hour', 'Min', 'Sec'])

    # --- PRE-FILTER TO AVOID COLUMN COLLISIONS ---
    df_athletes = df_athletes_raw[['Athlete_ID', 'Name', 'Gender', 'YOB', 'Nationality']]
    df_teams = df_teams_raw[['Team_ID', 'Name']].rename(columns={'Name': 'Team_Name'})
    df_races = df_races_raw[['Race_ID', 'Distance', 'Date', 'City', 'Prov', 'Country', 'Surface']].copy()
    df_races['Race_Distance'] = df_races['Distance']

    # Prepare final results, including unfinished races for profiles
    df_main = pd.merge(df_results, df_races, on='Race_ID', how='left')
    df_main['Is_Split'] = False


    # Prepare splits and retain their parent result IDs
    if not df_splits.empty:
        df_splits_expanded = pd.merge(df_splits, df_results[['Result_ID', 'Athlete_ID', 'Team_ID', 'Race_ID', 'Rank']], on='Result_ID', how='inner')
        df_splits_expanded = pd.merge(df_splits_expanded, df_races.drop(columns=['Distance']), on='Race_ID', how='left')
        df_splits_expanded['Is_Split'] = True
        

        
        df_all = pd.concat([df_main, df_splits_expanded], ignore_index=True)
    else:
        df_all = df_main

    df_all = pd.merge(df_all, df_athletes, on='Athlete_ID', how='left')
    df_all = pd.merge(df_all, df_teams, on='Team_ID', how='left')
    df_all['Team'] = df_all['Team_Name'].fillna('Unattached')

    df_all = df_all[df_all['Nationality'].str.upper() == 'CAN']

    for col in ['Hour', 'Min', 'Sec']:
        df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)
    df_all['Exact_Seconds'] = (df_all['Hour'] * 3600) + (df_all['Min'] * 60) + df_all['Sec']
    df_all = df_all[(~df_all['Is_Split']) | (df_all['Exact_Seconds'] > 0)]

    # Normalize distances for leaderboard filtering and personal bests.
    df_all['Dist_Check'] = pd.to_numeric(df_all['Distance'], errors='coerce').round(3)
    # Keep other distances for complete athlete profiles; leaderboards use the whitelist.

    df_all['WA Points'] = df_all.apply(
        lambda row: calculate_wa_points(row['Gender'], row['Distance'], row['Surface'], row['Exact_Seconds'], wa_table) if row['Exact_Seconds'] > 0 and (row['Is_Split'] or str(row['Rank']).strip().upper() not in ['DQ', 'DNF', 'NT']) else 0, 
        axis=1
    )

    def format_mark(row):
        total_s = row['Exact_Seconds']
        surf = str(row['Surface']).strip().title()
        status = str(row['Rank']).strip().upper()
        if not row['Is_Split'] and (status in ['DQ', 'DNF', 'NT'] or total_s <= 0):
            return status if status in ['DQ', 'DNF', 'NT'] else 'NT'

        if surf == 'Road':
            total_s = math.ceil(total_s)
            hh = int(total_s // 3600)
            mm = int((total_s % 3600) // 60)
            ss = int(total_s % 60)
            mark = f"{hh}:{mm:02d}:{ss:02d}" if hh > 0 else f"{mm:02d}:{ss:02d}"
        else:
            hh = int(total_s // 3600)
            mm = int((total_s % 3600) // 60)
            ss = total_s % 60
            mark = f"{hh}:{mm:02d}:{ss:05.2f}" if hh > 0 else f"{mm:02d}:{ss:05.2f}"
            
        if row.get('Is_Split', False):
            mark += "+"
            
        return mark

    df_all['Mark'] = df_all.apply(format_mark, axis=1)

    def format_location(row):
        country = str(row['Country']).strip().upper()
        city = str(row['City']).strip()
        prov = str(row['Prov']).strip() 
        
        if country in ['CAN', 'USA']:
            return f"{city}, {prov}"
        return f"{city}, {country}"

    df_all['Location'] = df_all.apply(format_location, axis=1)

    df_all['Year'] = pd.to_datetime(df_all['Date'], errors='coerce').dt.year

    backend_cols = ['Athlete_ID', 'Result_ID', 'Race_ID', 'Rank', 'Is_Split', 'Race_Distance', 'Dist_Check', 'Name', 'Gender', 'Mark', 'WA Points', 'Distance', 'Date', 'Location', 'Exact_Seconds', 'Year', 'YOB', 'Team']
    return df_all[backend_cols]

# 4. Building the User Interface
st.title("Canadian Racewalking Database")
data = load_data()

st.sidebar.header("Navigation")
if 'app_mode' not in st.session_state:
    st.session_state.app_mode = "Leaderboards"
st.sidebar.radio("Go to:", ["Leaderboards", "Athlete Profiles"], key='app_mode')
st.sidebar.divider()

if st.session_state.app_mode == "Leaderboards":
    st.write("All-time performances for Canadian athletes. Select an athlete's row to open their profile.")
    st.sidebar.header("Filter & Sort")
    sort_by = st.sidebar.radio("Sort By", ["Time", "WA Points"])
    best_only = st.sidebar.checkbox("Only show best by athlete")
    allowed_dists = [1.5, 1.609, 3.0, 5.0, 10.0, 15.0, 20.0, 21.1, 30.0, 35.0, 42.2, 50.0]
    leaderboard = data[data['Dist_Check'].isin(allowed_dists) & (data['Exact_Seconds'] > 0) & (data['Is_Split'] | ~data['Rank'].astype(str).str.strip().str.upper().isin(['DQ', 'DNF', 'NT']))]
    unique_numeric_dists = sorted(leaderboard['Distance'].dropna().astype(float).unique().tolist())
    display_dist_options = [format_distance_string(d) for d in unique_numeric_dists]
    if sort_by == "WA Points":
        display_dist_options = ["All Distances"] + display_dist_options
    selected_display_dist = st.sidebar.selectbox("Distance", display_dist_options)
    genders = sorted(leaderboard['Gender'].dropna().unique().tolist())
    selected_gender = st.sidebar.selectbox("Gender", genders)
    years = sorted(leaderboard['Year'].dropna().astype(int).unique().tolist(), reverse=True)
    selected_year = st.sidebar.selectbox("Year", ["All Years"] + years)

    filtered_data = leaderboard[leaderboard['Gender'] == selected_gender].copy()
    if selected_display_dist != "All Distances":
        offset = 1 if sort_by == "WA Points" else 0
        distance = unique_numeric_dists[display_dist_options.index(selected_display_dist) - offset]
        filtered_data = filtered_data[filtered_data['Distance'].astype(float) == distance]
    if selected_year != "All Years":
        filtered_data = filtered_data[filtered_data['Year'] == selected_year]
    if sort_by == "Time":
        filtered_data = filtered_data.sort_values('Exact_Seconds')
    else:
        filtered_data = filtered_data.sort_values(['WA Points', 'Exact_Seconds'], ascending=[False, True])
    filtered_data = filtered_data.reset_index(drop=True)
    filtered_data['Is_PB'] = ~filtered_data.duplicated(subset=['Athlete_ID'])
    filtered_data['Order'] = filtered_data['Is_PB'].cumsum().where(filtered_data['Is_PB'], '').astype(str)
    if best_only:
        filtered_data = filtered_data[filtered_data['Is_PB']].copy()
    filtered_data = filtered_data.reset_index(drop=True)
    filtered_data['Distance'] = filtered_data['Distance'].apply(format_distance_string)
    filtered_data = filtered_data.rename(columns={'Location': 'Competition Location', 'Rank': 'Finish'})
    columns = ['Order', 'Mark', 'WA Points', 'Name', 'YOB', 'Team', 'Date', 'Competition Location', 'Finish']
    if sort_by == "WA Points":
        columns = ['Order', 'WA Points', 'Name', 'Mark', 'Distance', 'YOB', 'Team', 'Date', 'Competition Location', 'Finish']

    def highlight_pb(row):
        return ['font-weight: bold' if filtered_data.loc[row.name, 'Is_PB'] else '' for _ in row]

    selection = st.dataframe(
        filtered_data[columns].style.apply(highlight_pb, axis=1),
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row",
        key='leaderboard_table',
    )
    if selection.selection.rows:
        selected_row = selection.selection.rows[0]
        if selected_row < len(filtered_data):
            st.session_state.selected_athlete_id = filtered_data.iloc[selected_row]['Athlete_ID']
            st.session_state.app_mode = "Athlete Profiles"
            st.rerun()

else:
    if 'leaderboard_table' in st.session_state:
        del st.session_state['leaderboard_table']
    st.sidebar.header("Profile Settings")
    athletes = data[['Athlete_ID', 'Name']].drop_duplicates().sort_values(['Name', 'Athlete_ID'])
    athlete_ids = athletes['Athlete_ID'].tolist()
    names = athletes.set_index('Athlete_ID')['Name'].to_dict()
    if st.session_state.get('selected_athlete_id') not in athlete_ids:
        st.session_state.selected_athlete_id = athlete_ids[0]
    selected_id = st.sidebar.selectbox(
        "Search Athlete", athlete_ids, format_func=lambda athlete_id: names[athlete_id],
        key='selected_athlete_id',
    )
    athlete_data = data[data['Athlete_ID'] == selected_id].copy()
    st.subheader(f"Results Profile: {names[selected_id]}")

    st.markdown("### Personal bests")
    pbs = (athlete_data[(athlete_data['Exact_Seconds'] > 0) & (athlete_data['Is_Split'] | ~athlete_data['Rank'].astype(str).str.strip().str.upper().isin(['DQ', 'DNF', 'NT']))].sort_values('Exact_Seconds')
           .drop_duplicates(subset=['Dist_Check'])
           .sort_values('Dist_Check').copy())
    pbs['Distance'] = pbs['Distance'].apply(format_distance_string)
    st.dataframe(pbs[['Distance', 'Mark', 'WA Points', 'Date', 'Location', 'Rank']].rename(
        columns={'Rank': 'Finish'}), use_container_width=True, hide_index=True)

    st.markdown("### Results by year")
    # A result can have splits even when its final mark was recorded as NT.
    races = athlete_data.sort_values(['Is_Split', 'Dist_Check']).drop_duplicates('Result_ID')
    races = races.sort_values('Date', ascending=False)
    for year, year_races in races.groupby('Year', sort=False, dropna=False):
        st.markdown(f"#### {int(year) if pd.notna(year) else 'Unknown year'}")
        for _, race in year_races.iterrows():
            parts = athlete_data[athlete_data['Result_ID'] == race['Result_ID']]
            final = parts[~parts['Is_Split']]
            mark = final.iloc[0]['Mark'] if not final.empty else 'NT'
            distance = format_distance_string(race['Race_Distance'])
            label = f"{race['Date']} ? {distance} ? {race['Location']} ? {mark} ? Finish: {race['Rank']}"
            with st.expander(label):
                st.write(f"Team: {race['Team']}")
                splits = parts[parts['Is_Split']].sort_values('Dist_Check').copy()
                if not splits.empty:
                    splits['Distance'] = splits['Distance'].apply(format_distance_string)
                    st.dataframe(splits[['Distance', 'Mark', 'WA Points']], use_container_width=True, hide_index=True)
                else:
                    st.caption("No splits recorded.")
