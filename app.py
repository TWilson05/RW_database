import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# 1. Page Config
st.set_page_config(page_title="Canadian Racewalk Database", layout="wide")

# 2. Secure Google Sheets Connection
@st.cache_resource
def get_gspread_client():
    # Streamlit securely pulls this from your Cloud settings, NOT your public code
    credentials_dict = st.secrets["gcp_service_account"]
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
    return gspread.authorize(creds)

# 3. Load and Merge Data
@st.cache_data(ttl=600) # Caches the data for 10 minutes
def load_data():
    gc = get_gspread_client()
    sh = gc.open("Canadian Racewalk") # Ensure this matches your sheet name

    # Pull the tables
    df_athletes = pd.DataFrame(sh.worksheet('Athletes').get_all_records())
    df_races = pd.DataFrame(sh.worksheet('Races').get_all_records())
    df_results = pd.DataFrame(sh.worksheet('Results').get_all_records())

    # Merge Results with Athlete Names and Race Info
    df_merged = pd.merge(df_results, df_athletes, on='Athlete_ID', how='left')
    df_merged = pd.merge(df_merged, df_races, on='Race_ID', how='left', suffixes=('_Athlete', '_Race'))

    # Format the Time nicely
    def format_time(h, m, s):
        if h > 0:
            return f"{int(h)}:{int(m):02d}:{float(s):04.1f}"
        else:
            return f"{int(m):02d}:{float(s):04.1f}"

    df_merged['Mark'] = df_merged.apply(lambda row: format_time(row['Hour'], row['Min'], row['Sec']), axis=1)
    
    # Calculate Total Seconds for accurate sorting
    df_merged['Total_Seconds'] = (df_merged['Hour'] * 3600) + (df_merged['Min'] * 60) + df_merged['Sec']

    # --- DATA CLEANUP ---
    # 1. Filter out DQs, DNFs, and any blank times (0 seconds)
    df_merged = df_merged[~df_merged['Rank'].astype(str).str.upper().isin(['DQ', 'DNF'])]
    df_merged = df_merged[df_merged['Total_Seconds'] > 0]

    # 2. Extract the Year from the Date column for our new filter
    df_merged['Year'] = pd.to_datetime(df_merged['Date'], errors='coerce').dt.year

    # Keep only the columns we want to work with
    display_cols = ['Name', 'Gender_Athlete', 'Mark', 'Distance', 'Date', 'City', 'Prov_Race', 'Total_Seconds', 'Year']
    df_clean = df_merged[display_cols]
    
    # Rename them back to clean names for the website display
    df_clean = df_clean.rename(columns={
        'Gender_Athlete': 'Gender',
        'Prov_Race': 'Prov'
    })
    
    return df_clean

# 4. Building the User Interface
st.title("Canadian Racewalking Database")
st.write("All-time performances and historical results.")

data = load_data()

# Sidebar Filters
st.sidebar.header("Filter Results")

# Distance Filter (Removed "All" - defaults to the first distance in the list)
distances = sorted(data['Distance'].dropna().unique().tolist())
selected_dist = st.sidebar.selectbox("Distance", distances)

# Gender Filter (Removed "All" - defaults to Male/Female based on your Athletes table)
genders = sorted(data['Gender'].dropna().unique().tolist())
selected_gender = st.sidebar.selectbox("Gender", genders)

# Year Filter (Includes "All Years")
# We convert the years to integers to remove the ".0" decimal that Pandas sometimes adds
years = sorted(data['Year'].dropna().astype(int).unique().tolist(), reverse=True)
selected_year = st.sidebar.selectbox("Year", ["All Years"] + years)

# Apply the Filters
# We strictly filter by Distance and Gender first
filtered_data = data[
    (data['Distance'] == selected_dist) & 
    (data['Gender'] == selected_gender)
].copy()

# Then we filter by Year if a specific year is chosen
if selected_year != "All Years":
    filtered_data = filtered_data[filtered_data['Year'] == selected_year]

# Sort by fastest time and drop the backend tracking columns
filtered_data = filtered_data.sort_values(by='Total_Seconds').reset_index(drop=True)
display_data = filtered_data.drop(columns=['Total_Seconds', 'Year'])

# Make the row numbers act as actual rankings (1, 2, 3...)
display_data.index += 1 

# Display the Table
st.dataframe(display_data, use_container_width=True)