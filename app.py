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
    is_road = (surf == 'Road')
    
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
    df_races = df_races_raw[['Race_ID', 'Distance', 'Date', 'City', 'Prov', 'Country', 'Surface']]

    df_main = pd.merge(df_results, df_races, on='Race_ID', how='left')
    df_main['Is_Split'] = False

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
    df_all = df_all[~df_all['Rank'].astype(str).str.upper().isin(['DQ', 'DNF'])]

    df_all['Exact_Seconds'] = (df_all['Hour'] * 3600) + (df_all['Min'] * 60) + df_all['Sec']
    df_all = df_all[df_all['Exact_Seconds'] > 0]

    df_all['WA Points'] = df_all.apply(
        lambda row: calculate_wa_points(row['Gender'], row['Distance'], row['Surface'], row['Exact_Seconds'], wa_table), 
        axis=1
    )

    def format_mark(row):
        total_s = row['Exact_Seconds']
        surf = str(row['Surface']).strip().title()
        
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

    backend_cols = ['Name', 'Gender', 'Mark', 'WA Points', 'Distance', 'Date', 'Location', 'Exact_Seconds', 'Year', 'YOB', 'Team']
    return df_all[backend_cols]

# 4. Building the User Interface
st.title("Canadian Racewalking Database")
data = load_data()

# --- APP NAVIGATION ---
st.sidebar.header("Navigation")
app_mode = st.sidebar.radio("Go to:", ["Leaderboards", "Athlete Profiles"])

st.sidebar.divider()

if app_mode == "Leaderboards":
    st.write("All-time performances for Canadian athletes.")
    st.sidebar.header("Filter & Sort")

    # --- Sort Toggle ---
    sort_by = st.sidebar.radio("Sort By", ["Time", "WA Points"])

    # Distance Logic
    unique_numeric_dists = sorted(data['Distance'].dropna().astype(float).unique().tolist())
    display_dist_options = [format_distance_string(d) for d in unique_numeric_dists]

    if sort_by == "WA Points":
        display_dist_options = ["All Distances"] + display_dist_options

    selected_display_dist = st.sidebar.selectbox("Distance", display_dist_options)

    genders = sorted(data['Gender'].dropna().unique().tolist())
    selected_gender = st.sidebar.selectbox("Gender", genders)

    years = sorted(data['Year'].dropna().astype(int).unique().tolist(), reverse=True)
    selected_year = st.sidebar.selectbox("Year", ["All Years"] + years)

    # --- APPLY FILTERS ---
    if selected_display_dist == "All Distances":
        filtered_data = data[data['Gender'] == selected_gender].copy()
    else:
        offset = 1 if sort_by == "WA Points" else 0
        selected_numeric_dist = unique_numeric_dists[display_dist_options.index(selected_display_dist) - offset]
        
        filtered_data = data[
            (data['Distance'].astype(float) == selected_numeric_dist) & 
            (data['Gender'] == selected_gender)
        ].copy()

    if selected_year != "All Years":
        filtered_data = filtered_data[filtered_data['Year'] == selected_year]

    # --- APPLY SORTING ---
    if sort_by == "Time":
        filtered_data = filtered_data.sort_values(by='Exact_Seconds', ascending=True).reset_index(drop=True)
    else:
        filtered_data = filtered_data.sort_values(by=['WA Points', 'Exact_Seconds'], ascending=[False, True]).reset_index(drop=True)

    # --- IDENTIFY PBs & ASSIGN RANK ---
    filtered_data['Is_PB'] = ~filtered_data.duplicated(subset=['Name'], keep='first')

    ranks = []
    current_rank = 1
    for is_pb in filtered_data['Is_PB']:
        if is_pb:
            ranks.append(str(current_rank))
            current_rank += 1
        else:
            ranks.append("") 

    filtered_data.insert(0, 'Order', ranks)
    filtered_data = filtered_data.rename(columns={'Location': 'Competition Location'})

    filtered_data['Distance'] = filtered_data['Distance'].apply(format_distance_string)

    # --- DYNAMIC COLUMN SELECTION ---
    if sort_by == "Time":
        final_display_columns = ['Order', 'Mark', 'WA Points', 'Name', 'YOB', 'Team', 'Date', 'Competition Location', 'Is_PB']
    else:
        final_display_columns = ['Order', 'WA Points', 'Name', 'Mark', 'Distance', 'YOB', 'Team', 'Date', 'Competition Location', 'Is_PB']

    display_data = filtered_data[final_display_columns]

    # --- Apply Bold Styling ---
    def highlight_pb(row):
        if row['Is_PB']:
            return ['font-weight: bold'] * len(row)
        return [''] * len(row)

    styled_dataframe = (
        display_data.style
        .apply(highlight_pb, axis=1)
        .hide(subset=['Is_PB'], axis="columns")
        .hide(axis="index")
    )

    st.dataframe(styled_dataframe, use_container_width=True)

# ---------------------------------------------------------
# NEW: ATHLETE PROFILES MODE
# ---------------------------------------------------------
elif app_mode == "Athlete Profiles":
    
    st.sidebar.header("Profile Settings")
    
    # Athlete Search Dropdown
    all_athletes = sorted(data['Name'].dropna().unique().tolist())
    selected_athlete = st.sidebar.selectbox("Search Athlete", all_athletes)
    
    # Filter data for the specific athlete
    athlete_data = data[data['Name'] == selected_athlete].copy()
    
    # Profile Filters
    unique_athlete_dists = sorted(athlete_data['Distance'].dropna().astype(float).unique().tolist())
    profile_dist_options = ["All Distances"] + [format_distance_string(d) for d in unique_athlete_dists]
    
    selected_profile_dist = st.sidebar.selectbox("Filter Distance", profile_dist_options)
    profile_sort_by = st.sidebar.radio("Sort Results By", ["Date (Most Recent)", "Time (Fastest)", "WA Points (Highest)"])

    # Apply Profile Distance Filter
    if selected_profile_dist != "All Distances":
        # Map the selected string back to the float value
        selected_numeric_dist = unique_athlete_dists[profile_dist_options.index(selected_profile_dist) - 1]
        athlete_data = athlete_data[athlete_data['Distance'].astype(float) == selected_numeric_dist]

    # Apply Profile Sorting
    if profile_sort_by == "Date (Most Recent)":
        # String sorting for YYYY-MM-DD works perfectly
        athlete_data = athlete_data.sort_values(by='Date', ascending=False)
    elif profile_sort_by == "Time (Fastest)":
        athlete_data = athlete_data.sort_values(by='Exact_Seconds', ascending=True)
    elif profile_sort_by == "WA Points (Highest)":
        athlete_data = athlete_data.sort_values(by=['WA Points', 'Exact_Seconds'], ascending=[False, True])

    athlete_data = athlete_data.reset_index(drop=True)
    
    # Format distances cleanly before display
    athlete_data['Distance'] = athlete_data['Distance'].apply(format_distance_string)

    # --- RENDER PROFILE UI ---
    st.subheader(f"Results Profile: {selected_athlete}")
    
    if athlete_data.empty:
        st.info(f"No results found for {selected_athlete} at this distance.")
    else:
        # Quick Stats Row
        total_races = len(athlete_data)
        st.markdown(f"**Total Results Shown:** {total_races}")
        
        # Display the Profile Table
        profile_display_cols = ['Date', 'Distance', 'Mark', 'WA Points', 'Location', 'Team']
        st.dataframe(athlete_data[profile_display_cols], use_container_width=True, hide_index=True)
