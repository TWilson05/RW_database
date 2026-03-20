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

# 3. Load, Merge, and Clean Data
@st.cache_data(ttl=600)
def load_data():
    gc = get_gspread_client()
    sh = gc.open("Canadian Racewalk")

    # Pull the tables
    df_athletes = pd.DataFrame(sh.worksheet('Athletes').get_all_records())
    df_races = pd.DataFrame(sh.worksheet('Races').get_all_records())
    df_results = pd.DataFrame(sh.worksheet('Results').get_all_records())
    df_teams = pd.DataFrame(sh.worksheet('Teams').get_all_records())

    # --- MERGING ---
    # Merge Results with Athletes
    df_merged = pd.merge(df_results, df_athletes, on='Athlete_ID', how='left')
    
    # Merge with Races (Handles duplicate 'Prov' and 'Gender' columns)
    df_merged = pd.merge(df_merged, df_races, on='Race_ID', how='left', suffixes=('_Athlete', '_Race'))
    
    # Merge with Teams (Handles duplicate 'Name' columns: Athlete Name vs Team Name)
    df_merged = pd.merge(df_merged, df_teams, on='Team_ID', how='left', suffixes=('', '_Team'))
    df_merged['Team'] = df_merged['Name_Team'].fillna('Unattached')

    # --- FILTERING ---
    # 1. Only Canadian Athletes
    df_merged = df_merged[df_merged['Nationality'].str.upper() == 'CAN']

    # 2. Filter out DQs, DNFs
    df_merged = df_merged[~df_merged['Rank'].astype(str).str.upper().isin(['DQ', 'DNF'])]

    # Calculate exact total seconds first for accurate math/sorting
    df_merged['Exact_Seconds'] = (df_merged['Hour'] * 3600) + (df_merged['Min'] * 60) + df_merged['Sec']
    df_merged = df_merged[df_merged['Exact_Seconds'] > 0]

    # --- FORMATTING ---
    # Smart Time Formatting (Road vs Track)
    def format_mark(row):
        total_s = row['Exact_Seconds']
        surface = str(row['Surface']).strip().upper()
        
        if surface == 'ROAD':
            # Track & Field Rules: Road times round UP to the nearest full second
            total_s = math.ceil(total_s)
            hh = int(total_s // 3600)
            mm = int((total_s % 3600) // 60)
            ss = int(total_s % 60)
            if hh > 0:
                return f"{hh}:{mm:02d}:{ss:02d}"
            return f"{mm:02d}:{ss:02d}"
        else:
            # Track/Indoor: Keep up to 2 decimal places (.00)
            hh = int(total_s // 3600)
            mm = int((total_s % 3600) // 60)
            ss = total_s % 60
            if hh > 0:
                return f"{hh}:{mm:02d}:{ss:05.2f}"
            return f"{mm:02d}:{ss:05.2f}"
            
    df_merged['Mark'] = df_merged.apply(format_mark, axis=1)

    # Smart Location Formatting (CAN/USA vs International)
    def format_location(row):
        country = str(row['Country']).strip().upper()
        city = str(row['City']).strip()
        prov = str(row['Prov_Race']).strip()
        
        if country in ['CAN', 'USA']:
            return f"{city}, {prov}"
        return f"{city}, {country}"

    df_merged['Location'] = df_merged.apply(format_location, axis=1)

    # Extract Year
    df_merged['Year'] = pd.to_datetime(df_merged['Date'], errors='coerce').dt.year

    # Keep only the columns needed for the backend and the final display
    backend_cols = ['Name', 'Gender_Athlete', 'Mark', 'Distance', 'Date', 'Location', 'Exact_Seconds', 'Year', 'YOB', 'Team']
    df_clean = df_merged[backend_cols].rename(columns={'Gender_Athlete': 'Gender'})
    
    return df_clean

# 4. Building the User Interface
st.title("Canadian Racewalking Database")
st.write("All-time performances for Canadian athletes.")

data = load_data()

# Sidebar Filters
st.sidebar.header("Filter Results")

# Distance Filter (Defaults to the first distance)
distances = sorted(data['Distance'].dropna().unique().tolist())
selected_dist = st.sidebar.selectbox("Distance", distances)

# Gender Filter (Defaults to the first gender)
genders = sorted(data['Gender'].dropna().unique().tolist())
selected_gender = st.sidebar.selectbox("Gender", genders)

# Year Filter (Includes "All Years")
years = sorted(data['Year'].dropna().astype(int).unique().tolist(), reverse=True)
selected_year = st.sidebar.selectbox("Year", ["All Years"] + years)

# Apply the Filters
filtered_data = data[
    (data['Distance'] == selected_dist) & 
    (data['Gender'] == selected_gender)
].copy()

if selected_year != "All Years":
    filtered_data = filtered_data[filtered_data['Year'] == selected_year]

# Sort by the fastest EXACT time
filtered_data = filtered_data.sort_values(by='Exact_Seconds').reset_index(drop=True)

# Create the specific display columns requested
filtered_data.insert(0, 'Order', range(1, len(filtered_data) + 1)) # Creates 1, 2, 3...
filtered_data = filtered_data.rename(columns={'Location': 'Competition Location'})

final_display_columns = ['Order', 'Mark', 'Name', 'YOB', 'Team', 'Date', 'Competition Location']
display_data = filtered_data[final_display_columns]

# Display the Table (hide_index=True removes the default pandas row numbers since we made an 'Order' column)
st.dataframe(display_data, use_container_width=True, hide_index=True)