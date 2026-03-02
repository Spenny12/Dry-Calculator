import streamlit as st
import pandas as pd
import requests
import json
import os
import math

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

# --- 3. TEMPLEOSRS API (KC DATA) ---
@st.cache_data(ttl=3600)
def fetch_player_kc(player_name):
    url = f"https://templeosrs.com/api/player_stats.php?player={player_name}&bosses=1"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("data", {})
    except Exception:
        return None

# --- 4. COLLECTIONLOG.NET API (SLOT DATA) ---
@st.cache_data(ttl=3600)
def fetch_clog_slots(player_name):
    url = f"https://api.collectionlog.net/collectionlog/user/{player_name}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        clog_stats = {}
        tabs = data.get("collectionLog", {}).get("tabs", {})

        for tab_name, pages in tabs.items():
            for page_name, page_data in pages.items():
                items = page_data.get("items", [])
                total_slots = len(items)
                actual_slots = sum(1 for item in items if item.get("obtained"))

                clog_stats[page_name.lower()] = {
                    "actual_slots": actual_slots,
                    "total_slots": total_slots
                }
        return clog_stats
    except Exception:
        return None

# --- 5. PROGRESS-WEIGHTED LUCK LOGIC (LOGARITHMIC) ---
def determine_progress_luck(actual_kc, expected_kc, actual_slots, total_slots, activity_name=""):
    if actual_kc == 0 or expected_kc == 0 or total_slots == 0:
        return "Not Started", 0.0, 0.0

    kc_percent = actual_kc / expected_kc

    # 1. Determine the curve steepness (a)
    # Barrows has no pets/mega-rares, so it gets a flatter curve.
    a = 2 if "barrows" in activity_name.lower() else 15

    # 2. Apply the Logarithmic Formula
    s = math.log(1 + a * kc_percent) / math.log(1 + a)

    # 3. Calculate Expected Slots and cap it at the Total Slots
    expected_slots_at_kc = total_slots * s
    if expected_slots_at_kc > total_slots:
        expected_slots_at_kc = total_slots

    # 4. Calculate Luck Ratio
    if actual_slots == total_slots:
        # Greenlogged! Math simplifies to actual / expected
        ratio = actual_kc / expected_kc
    elif actual_slots == 0:
        # No drops yet. Are they dry for a drop, or is it too early?
        if expected_slots_at_kc <= 1.0:
            ratio = 1.0 # On-Rate
        else:
            ratio = expected_slots_at_kc # Dry by the number of slots missed
    else:
        # Core Formula: What you should have / What you actually have
        ratio = expected_slots_at_kc / actual_slots

    # 5. Determine Status
    if ratio <= 0.5: status = "Spooned 🥄"
    elif ratio <= 0.9: status = "Wet 💧"
    elif ratio <= 1.1: status = "On-Rate 🎯"
    elif ratio <= 1.5: status = "Dry 🏜️"
    else: status = "Very Dry 💀"

    return status, ratio, expected_slots_at_kc

# --- 6. MAIN APP ---
def main():
    st.set_page_config(page_title="OSRS Clog Luck Analyzer", layout="wide")
    st.title("OSRS Collection Log Luck Analyzer")
    st.markdown("Analyze how 'wet' or 'dry' your account is based on expected hours and your actual Collection Log progress using a logarithmic curve.")

    clog_data = load_all_clog_data()

    player_name = st.text_input("Enter OSRS Username:", value="Spencejliv", key="user_input_name")
    filter_type = st.radio("Filter By:", ["All", "Boss", "Raid", "Clue"], horizontal=True, key="filter_selection")

    if st.button("Analyze Account", type="primary", key="main_analyze_btn"):
        if not player_name:
            st.warning("Please enter a username.")
            return

        with st.spinner(f"Fetching hiscores and Collection Log for {player_name}..."):
            player_stats = fetch_player_kc(player_name)
            clog_api_data = fetch_clog_slots(player_name)

        with st.expander("🔍 API Debug (Click to view raw TempleOSRS data)"):
            if player_stats:
                st.json(player_stats)
            else:
                st.write("No data returned from API.")

        if player_stats is None:
            st.error("Could not connect to TempleOSRS. The API might be down.")
            return
        elif not player_stats:
            st.warning(f"No hiscore data found for '{player_name}'. Make sure they are tracked on TempleOSRS.")
            return

        has_clog_data = True
        if not clog_api_data:
            has_clog_data = False
            st.warning(f"⚠️ We couldn't find Collection Log data for '{player_name}' on collectionlog.net. Luck is being calculated assuming all logs are completed! (Upload your log via the RuneLite plugin for accuracy).")

        results = []
        total_ratio = 0
        valid_activities = 0

        # Flatten and lowercase API stats
        safe_stats = {str(k).lower(): v for k, v in player_stats.items()}
        if "bosses" in safe_stats and isinstance(safe_stats["bosses"], dict):
            for k, v in safe_stats["bosses"].items():
                safe_stats[str(k).lower()] = v

        for api_key, details in clog_data.items():
            if filter_type != "All" and details.get("type") != filter_type:
                continue

            actual_kc = safe_stats.get(api_key.lower(), 0)
            expected_kc = details.get("ekc", 0)
            page_name = details["name"].lower()

            # Extract actual vs total slots
            if has_clog_data and page_name in clog_api_data:
                actual_slots = clog_api_data[page_name]["actual_slots"]
                total_slots = clog_api_data[page_name]["total_slots"]
            else:
                actual_slots = 1
                total_slots = 1

            if actual_kc > 0 and expected_kc > 0:
                status, ratio, exp_slots = determine_progress_luck(
                    actual_kc, expected_kc, actual_slots, total_slots, details["name"]
                )

                results.append({
                    "Activity": details["name"],
                    "Clog Progress": f"{actual_slots}/{total_slots}" if has_clog_data else "Unknown",
                    "Expected Slots": round(exp_slots, 1) if has_clog_data else "N/A",
                    "Actual KC": actual_kc,
                    "Expected KC": expected_kc,
                    "Ratio": round(ratio, 2),
                    "Status": status
                })
