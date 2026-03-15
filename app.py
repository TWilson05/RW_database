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
@st.cache_data(ttl=600) # Caches the data for 10 minutes so your site is lightning fast
def load_data():
    gc = get_gspread_client()
    sh = gc.open("Canadian Racewalk") # Ensure this exactly matches your sheet name

    # Pull the tables
    df_athletes = pd.DataFrame(sh.worksheet('Athletes').get_all_records())
    df_races = pd.DataFrame(sh.worksheet('Races').get_all_records())
    df_results = pd.DataFrame(sh.worksheet('Results').get_all_records())

    # Merge Results with Athlete Names and Race Info
    df_merged = pd.merge(df_results, df_athletes, on='Athlete_ID', how='left')
    df_merged = pd.merge(df_merged, df_races, on='Race_ID', how='left')

    # Format the Time nicely
    def format_time(h, m, s):
        if h > 0:
            return f"{int(h)}:{int(m):02d}:{float(s):04.1f}"
        else:
            return f"{int(m):02d}:{float(s):04.1f}"

    df_merged['Mark'] = df_merged.apply(lambda row: format_time(row['Hour'], row['Min'], row['Sec']), axis=1)
    
    # Calculate Total Seconds for accurate sorting
    df_merged['Total_Seconds'] = (df_merged['Hour'] * 3600) + (df_merged['Min'] * 60) + df_merged['Sec']

    # Keep only the columns we want the public to see
    display_cols = ['Name', 'Gender', 'Mark', 'Distance', 'Date', 'City', 'Prov', 'Total_Seconds']
    return df_merged[display_cols]

# 4. Building the User Interface
st.title("Canadian Racewalking Database")
st.write("All-time performances and historical results.")

data = load_data()

# Sidebar Filters
st.sidebar.header("Filter Results")

# Distance Filter
distances = sorted(data['Distance'].dropna().unique().tolist())
selected_dist = st.sidebar.selectbox("Distance", ["All"] + distances)

# Gender Filter
genders = sorted(data['Gender'].dropna().unique().tolist())
selected_gender = st.sidebar.selectbox("Gender", ["All"] + genders)

# Apply the Filters
filtered_data = data.copy()
if selected_dist != "All":
    filtered_data = filtered_data[filtered_data['Distance'] == selected_dist]
if selected_gender != "All":
    filtered_data = filtered_data[filtered_data['Gender'] == selected_gender]

# Sort by fastest time and drop the hidden seconds column
filtered_data = filtered_data.sort_values(by='Total_Seconds').reset_index(drop=True)
display_data = filtered_data.drop(columns=['Total_Seconds'])
display_data.index += 1 # Make the row numbers act as actual rankings

# Display the Table
st.dataframe(display_data, use_container_width=True)