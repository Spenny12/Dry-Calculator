import streamlit as st
import pandas as pd
import requests
import json
import os

# --- 1. HARDCODED RAIDS DATA ---
RAIDS_DATA = {
    "chambers_of_xeric": {
        "name": "Chambers of Xeric",
        "type": "Raid",
        "ekc": round(850 / (30 / 60)),
        "kph": 2.0
    },
    "theatre_of_blood": {
        "name": "Theatre of Blood",
        "type": "Raid",
        "ekc": round(636 / (20 / 60)),
        "kph": 3.0
    },
    "tombs_of_amascut": {
        "name": "Tombs of Amascut",
        "type": "Raid",
        "ekc": round(692 / (35 / 60)),
        "kph": round(60 / 35, 2)
    }
}

# --- 2. DATA LOADING ---
@st.cache_data
def load_all_clog_data():
    combined_data = {}

    if os.path.exists("boss_clog_data.json"):
        with open("boss_clog_data.json", "r") as f:
            bosses = json.load(f)
            for k, v in bosses.items():
                v["type"] = "Boss"
            combined_data.update(bosses)

    if os.path.exists("clue_clog_data.json"):
        with open("clue_clog_data.json", "r") as f:
            clues = json.load(f)
            for k, v in clues.items():
                v["type"] = "Clue"
            combined_data.update(clues)

    combined_data.update(RAIDS_DATA)
    return combined_data

# --- 3. BULLETPROOF API INTEGRATION ---
@st.cache_data(ttl=3600)
def fetch_player_data(player_name):
    url = f"https://templeosrs.com/api/player_stats.php?player={player_name}&bosses=1"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Instead of looking for a specific 'bosses' dictionary,
        # we return the entire 'data' block just in case it's flat.
        return data.get("data", {})
    except Exception as e:
        return None

# --- 4. LUCK LOGIC ---
def determine_luck(actual_kc, ekc):
    if actual_kc == 0 or not ekc:
        return "Not Started", 0.0
    ratio = actual_kc / ekc
    if ratio <= 0.5: status = "Spooned 🥄"
    elif ratio <= 0.9: status = "Wet 💧"
    elif ratio <= 1.1: status = "On-Rate 🎯"
    elif ratio <= 1.5: status = "Dry 🏜️"
    else: status = "Very Dry 💀"
    return status, ratio

# --- 5. MAIN APP ---
def main():
    st.set_page_config(page_title="OSRS Clog Luck Analyzer", layout="wide")
    st.title("OSRS Collection Log Luck Analyzer")
    st.markdown("Analyze how 'wet' or 'dry' your account is based on expected hours to greenlog.")

    clog_data = load_all_clog_data()

    player_name = st.text_input("Enter OSRS Username:", value="Spencejliv", key="user_input_name")
    filter_type = st.radio("Filter By:", ["All", "Boss", "Raid", "Clue"], horizontal=True, key="filter_selection")

    if st.button("Analyze Account", type="primary", key="main_analyze_btn"):
        if not player_name:
            st.warning("Please enter a username.")
            return

        with st.spinner(f"Fetching hiscores for {player_name}..."):
            player_stats = fetch_player_data(player_name)

        # --- NEW DEBUGGER ---
        with st.expander("🔍 API Debug (Click to view raw TempleOSRS data)"):
            if player_stats:
                st.json(player_stats)
            else:
                st.write("No data returned from API.")

        if player_stats is None:
            st.error("Could not connect to TempleOSRS. The API might be down.")
        elif not player_stats:
            st.warning(f"No data found for '{player_name}'. Make sure they are tracked on TempleOSRS.")
        else:
            results = []
            total_ratio = 0
            valid_activities = 0

            # Make the API dictionary entirely case-insensitive and flat for safe searching
            safe_stats = {str(k).lower(): v for k, v in player_stats.items()}

            # If temple nests them under "bosses" anyway, flatten it out
            if "bosses" in safe_stats and isinstance(safe_stats["bosses"], dict):
                for k, v in safe_stats["bosses"].items():
                    safe_stats[str(k).lower()] = v

            for api_key, details in clog_data.items():
                if filter_type != "All" and details.get("type") != filter_type:
                    continue

                # Check our safe lowercase dictionary
                actual_kc = safe_stats.get(api_key.lower(), 0)
                expected_kc = details.get("ekc", 0)

                if actual_kc > 0 and expected_kc > 0:
                    status, ratio = determine_luck(actual_kc, expected_kc)
                    results.append({
                        "Activity": details["name"],
                        "Type": details.get("type"),
                        "Actual KC": actual_kc,
                        "Expected KC": expected_kc,
                        "Ratio": round(ratio, 2),
                        "Status": status
                    })
                    total_ratio += ratio
                    valid_activities += 1

            if results:
                df = pd.DataFrame(results).sort_values(by="Ratio", ascending=False)
                st.dataframe(df, use_container_width=True, hide_index=True)

                st.divider()
                avg_ratio = total_ratio / valid_activities
                overall_status, _ = determine_luck(avg_ratio, 1.0)

                c1, c2, c3 = st.columns(3)
                c1.metric("Overall Luck", overall_status)
                c2.metric("Average Ratio", f"{avg_ratio:.2f}")
                c3.metric("Activities Tracked", valid_activities)
            else:
                st.info("The player exists, but no KC matched our database. Try checking the 🔍 API Debug dropdown above to see what names TempleOSRS is using for bosses!")

if __name__ == "__main__":
    main()
