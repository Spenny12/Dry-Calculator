import streamlit as st
import pandas as pd
import requests
import json
import os

# --- 1. HARDCODED RAIDS DATA ---
# Calculated Expected KC (EKC) = Expected Hours / Avg Hours per Kill
RAIDS_DATA = {
    "chambers_of_xeric": {
        "name": "Chambers of Xeric",
        "type": "Raid",
        "ekc": round(850 / (30 / 60)),  # 1700 KC
        "kph": 2.0
    },
    "theatre_of_blood": {
        "name": "Theatre of Blood",
        "type": "Raid",
        "ekc": round(636 / (20 / 60)),  # 1908 KC
        "kph": 3.0
    },
    "tombs_of_amascut": {
        "name": "Tombs of Amascut",
        "type": "Raid",
        "ekc": round(692 / (35 / 60)),  # ~1186 KC
        "kph": round(60 / 35, 2)
    }
}

# --- 2. DATA LOADING ---
@st.cache_data
def load_all_clog_data():
    """Loads JSON data and merges it with hardcoded raids."""
    combined_data = {}
    
    # Load Bosses
    if os.path.exists("boss_clog_data.json"):
        with open("boss_clog_data.json", "r") as f:
            bosses = json.load(f)
            # Add a 'type' tag for UI filtering later
            for k, v in bosses.items():
                v["type"] = "Boss"
            combined_data.update(bosses)
    else:
        st.warning("Could not find boss_clog_data.json. Make sure it's in the same folder.")

    # Load Clues
    if os.path.exists("clue_clog_data.json"):
        with open("clue_clog_data.json", "r") as f:
            clues = json.load(f)
            for k, v in clues.items():
                v["type"] = "Clue"
            combined_data.update(clues)
    else:
        st.warning("Could not find clue_clog_data.json. Make sure it's in the same folder.")

    # Inject Raids
    combined_data.update(RAIDS_DATA)
    
    return combined_data

# --- 3. TEMPLEOSRS API INTEGRATION ---
@st.cache_data(ttl=3600)
def fetch_player_data(player_name):
    """Fetches boss and clue/misc stats from TempleOSRS."""
    # We request bosses=1 to get standard boss KCs. 
    # Clues are usually bundled in the API's top-level or under 'misc', but Temple 
    # often returns everything in one large dump if we just query the player.
    url = f"https://templeosrs.com/api/player_stats.php?player={player_name}&bosses=1"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "error" in data:
            st.error(f"TempleOSRS Error: {data['error']}")
            return None
            
        # Temple returns stats under data -> bosses
        return data.get("data", {}).get("bosses", {})
        
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to fetch data for {player_name}. Error: {e}")
        return None

# --- 4. LUCK LOGIC ---
def determine_luck(actual_kc, ekc):
    if actual_kc == 0 or pd.isna(actual_kc):
        return "Not Started", 0.0
    
    ratio = actual_kc / ekc
    
    if ratio <= 0.5: status = "Spooned 🥄"
    elif ratio <= 0.9: status = "Wet 💧"
    elif ratio <= 1.1: status = "On-Rate 🎯"
    elif ratio <= 1.5: status = "Dry 🏜️"
    else: status = "Very Dry 💀"
        
    return status, ratio

# --- 5. MAIN APP UI ---
def main():
    st.set_page_config(page_title="OSRS Clog Luck Analyzer", layout="wide")
    st.title("OSRS Collection Log Luck Analyzer")
    st.markdown("Compare your actual KC against the Expected KC (EKC) required to greenlog bosses, clues, and raids.")

    # 1. Load the unified dataset
    clog_data = load_all_clog_data()
    
    if not clog_data:
        st.error("No data loaded. Please ensure your JSON files are present.")
        return

    # 2. User Input
    player_name = st.text_input("Enter OSRS Username:", "Zezima")
    
    # Optional filtering
    filter_type = st.radio("Filter By:", ["All", "Boss", "Raid", "Clue"], horizontal=True)

    if st.button("Analyze Account", type="primary"):
        with st.spinner(f"Fetching hiscores for {player_name}..."):
            player_stats = fetch_player_data(player_name)
            
        if player_stats:
            results = []
            total_ratio = 0
            valid_activities = 0
            
            # 3. Process Data
            for api_key, details in clog_data.items():
                # Apply UI Filter
                if filter_type != "All" and details.get("type") != filter_type:
                    continue
                
                # Retrieve actual KC from Temple (defaults to 0 if not found)
                actual_kc = player_stats.get(api_key, 0)
                expected_kc = details["ekc"]
                
                # Only show activities the player has actually started doing
                if actual_kc > 0:
                    status, ratio = determine_luck(actual_kc, expected_kc)
                    results.append({
                        "Activity": details["name"],
                        "Type": details.get("type", "Unknown"),
                        "Actual KC": actual_kc,
                        "Expected KC": expected_kc,
                        "Ratio": round(ratio, 2),
                        "Status": status
                    })
                    total_ratio += ratio
                    valid_activities += 1
            
            # 4. Display Results
            if results:
                df_results = pd.DataFrame(results)
                
                # Sort by Ratio (Highest to Lowest, so driest is at the top)
                df_results = df_results.sort_values(by="Ratio", ascending=False).reset_index(drop=True)
                
                # Style the dataframe slightly
                st.dataframe(
                    df_results, 
                    use_container_width=True,
                    column_config={
                        "Ratio": st.column_config.NumberColumn(
                            "Completion Ratio (Actual/EKC)",
                            help="Over 1.0 means you are past the expected completion rate (Dry). Under 1.0 means you are under (Wet/Spooned).",
                            format="%.2f"
                        )
                    }
                )
                
                # 5. Overall Account Summary
                st.divider()
                st.subheader(f"Overall Account Luck: {player_name}")
                
                overall_ratio = total_ratio / valid_activities
                overall_status, _ = determine_luck(overall_ratio, 1.0) # Base is 1.0 for the ratio average
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Overall Status", overall_status)
                col2.metric("Average Ratio", f"{overall_ratio:.2f}")
                col3.metric("Activities Logged", valid_activities)
                
            else:
                st.warning("No tracked KC found for this player in the selected categories.")

if __name__ == "__main__":
    main()
