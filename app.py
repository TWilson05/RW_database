import streamlit as st
import pandas as pd
import gspread
import math
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

# 3. Load, Merge, and Clean Data
@st.cache_data(ttl=600)
def load_data():
    gc = get_gspread_client()
    sh = gc.open("Canadian Racewalk")

    # Pull the core tables
    df_athletes = pd.DataFrame(sh.worksheet('Athletes').get_all_records())
    df_races = pd.DataFrame(sh.worksheet('Races').get_all_records())
    df_results = pd.DataFrame(sh.worksheet('Results').get_all_records())
    df_teams = pd.DataFrame(sh.worksheet('Teams').get_all_records())
    
    # Attempt to pull Splits
    try:
        df_splits = pd.DataFrame(sh.worksheet('Splits').get_all_records())
    except gspread.exceptions.WorksheetNotFound:
        df_splits = pd.DataFrame(columns=['Result_ID', 'Distance', 'Hour', 'Min', 'Sec'])

    # --- MERGING MAIN RESULTS ---
    df_main = pd.merge(df_results, df_races, on='Race_ID', how='left', suffixes=('', '_Race'))
    df_main['Is_Split'] = False

    # --- MERGING SPLITS ---
    if not df_splits.empty:
        df_splits_expanded = pd.merge(df_splits, df_results[['Result_ID', 'Athlete_ID', 'Team_ID', 'Race_ID', 'Rank']], on='Result_ID', how='inner')
        df_splits_expanded = pd.merge(df_splits_expanded, df_races.drop(columns=['Distance']), on='Race_ID', how='left')
        df_splits_expanded['Is_Split'] = True
        df_all = pd.concat([df_main, df_splits_expanded], ignore_index=True)
    else:
        df_all = df_main

    # --- FINAL METADATA MERGES ---
    df_all = pd.merge(df_all, df_athletes, on='Athlete_ID', how='left', suffixes=('_Race', '_Athlete'))
    df_all = df_all.rename(columns={'Gender_Athlete': 'Gender'})
    
    df_all = pd.merge(df_all, df_teams, on='Team_ID', how='left', suffixes=('', '_Team'))
    df_all['Team'] = df_all['Name_Team'].fillna('Unattached')

    # --- DATA CLEANING & RULES ---
    df_all = df_all[df_all['Nationality'].str.upper() == 'CAN']
    df_all = df_all[~df_all['Rank'].astype(str).str.upper().isin(['DQ', 'DNF'])]

    df_all['Exact_Seconds'] = (df_all['Hour'] * 3600) + (df_all['Min'] * 60) + df_all['Sec']
    df_all = df_all[df_all['Exact_Seconds'] > 0]

    # --- FORMATTING FUNCTIONS ---
    def format_mark(row):
        total_s = row['Exact_Seconds']
        surface = str(row['Surface']).strip().upper()
        
        if surface == 'ROAD':
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
        prov = str(row['Prov_Race']).strip()
        
        if country in ['CAN', 'USA']:
            return f"{city}, {prov}"
        return f"{city}, {country}"

    df_all['Location'] = df_all.apply(format_location, axis=1)

    df_all['Year'] = pd.to_datetime(df_all['Date'], errors='coerce').dt.year

    backend_cols = ['Name', 'Gender', 'Mark', 'Distance', 'Date', 'Location', 'Exact_Seconds', 'Year', 'YOB', 'Team']
    return df_all[backend_cols]

# 4. Building the User Interface
st.title("Canadian Racewalking Database")
st.write("All-time performances for Canadian athletes.")

data = load_data()

st.sidebar.header("Filter Results")

# --- UI Distance Logic ---
unique_numeric_dists = sorted(data['Distance'].dropna().astype(float).unique().tolist())
display_dist_options = [format_distance_string(d) for d in unique_numeric_dists]
selected_display_dist = st.sidebar.selectbox("Distance", display_dist_options)
selected_numeric_dist = unique_numeric_dists[display_dist_options.index(selected_display_dist)]

# Gender Filter
genders = sorted(data['Gender'].dropna().unique().tolist())
selected_gender = st.sidebar.selectbox("Gender", genders)

# Year Filter
years = sorted(data['Year'].dropna().astype(int).unique().tolist(), reverse=True)
selected_year = st.sidebar.selectbox("Year", ["All Years"] + years)

# Apply the Filters
filtered_data = data[
    (data['Distance'].astype(float) == selected_numeric_dist) & 
    (data['Gender'] == selected_gender)
].copy()

if selected_year != "All Years":
    filtered_data = filtered_data[filtered_data['Year'] == selected_year]

# Sort by the fastest EXACT time
filtered_data = filtered_data.sort_values(by='Exact_Seconds').reset_index(drop=True)

# --- NEW LOGIC: Identify PBs and Rank ---
# Flag the first occurrence of each name as their Personal Best (PB)
filtered_data['Is_PB'] = ~filtered_data.duplicated(subset=['Name'], keep='first')

# Create the specific Order column
ranks = []
current_rank = 1
for is_pb in filtered_data['Is_PB']:
    if is_pb:
        ranks.append(str(current_rank))
        current_rank += 1
    else:
        ranks.append("") # Leave blank if it's not a PB

filtered_data.insert(0, 'Order', ranks)
filtered_data = filtered_data.rename(columns={'Location': 'Competition Location'})

# We keep 'Is_PB' in this list temporarily so the styler can read it
final_display_columns = ['Order', 'Mark', 'Name', 'YOB', 'Team', 'Date', 'Competition Location', 'Is_PB']
display_data = filtered_data[final_display_columns]

# --- NEW LOGIC: Apply Bold Styling ---
def highlight_pb(row):
    # If the row is a PB, return CSS to bold every column in that row
    if row['Is_PB']:
        return ['font-weight: bold'] * len(row)
    return [''] * len(row)

# Apply the style, then hide the 'Is_PB' tracking column and the default index
styled_dataframe = (
    display_data.style
    .apply(highlight_pb, axis=1)
    .hide(subset=['Is_PB'], axis="columns")
    .hide(axis="index")
)

# Display the styled Table
st.dataframe(styled_dataframe, use_container_width=True)