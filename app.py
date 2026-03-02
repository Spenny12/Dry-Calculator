import streamlit as st
import pandas as pd
import requests
import json
import os
import math

# 1. Page Config MUST be the very first command
st.set_page_config(page_title="OSRS Clog Luck Analyzer", layout="wide")

# --- DATA & CONSTANTS ---
# Using the Raids data provided: Hours / (Mins per KC / 60)
RAIDS_DATA = {
    "chambers_of_xeric": {"name": "Chambers of Xeric", "type": "Raid", "ekc": 1700, "kph": 2.0},
    "theatre_of_blood": {"name": "Theatre of Blood", "type": "Raid", "ekc": 1908, "kph": 3.0},
    "tombs_of_amascut": {"name": "Tombs of Amascut", "type": "Raid", "ekc": 1186, "kph": 1.71}
}

@st.cache_data
def load_all_clog_data():
    """Loads JSON files and merges with hardcoded raids."""
    combined = {}
    for filename, activity_type in [("boss_clog_data.json", "Boss"), ("clue_clog_data.json", "Clue")]:
        if os.path.exists(filename):
            try:
                with open(filename, "r") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        v["type"] = activity_type
                        combined[k] = v
            except Exception as e:
                st.error(f"Error loading {filename}: {e}")
    combined.update(RAIDS_DATA)
    return combined

# --- API FUNCTIONS ---
@st.cache_data(ttl=3600)
def fetch_player_kc(player_name):
    """Fetches Boss KC from TempleOSRS."""
    url = f"https://templeosrs.com/api/player_stats.php?player={player_name}&bosses=1"
    try:
        r = requests.get(url, timeout=10)
        return r.json().get("data", {})
    except: return None

@st.cache_data(ttl=3600)
def fetch_clog_slots(player_name):
    """Fetches Slot counts from collectionlog.net (Full Drill-down)."""
    url = f"https://api.collectionlog.net/collectionlog/user/{player_name}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200: return None
        data = r.json()
        clog_stats = {}

        # Structure: data -> collectionLog -> tabs -> tab_name -> page_name
        tabs = data.get("collectionLog", {}).get("tabs", {})
        for tab in tabs.values():
            for page_name, page_data in tab.items():
                items = page_data.get("items", [])
                clog_stats[page_name.lower()] = {
                    "actual": sum(1 for i in items if i.get("obtained")),
                    "total": len(items)
                }
        return clog_stats
    except: return None

# --- LUCK LOGIC (LOGARITHMIC) ---
def determine_luck_v2(actual_kc, expected_kc, actual_slots, total_slots, name=""):
    """Calculates luck based on KC progress vs Slot expectation."""
    if actual_kc <= 0 or expected_kc <= 0 or total_slots <= 0:
        return "Not Started", 1.0, 0.0

    # KC Percent Progress
    p = actual_kc / expected_kc

    # 'a' is the steepness factor. 15 = Heavy Pet Tail, 2 = Linear/Even distribution.
    a = 2 if "barrows" in name.lower() or "clue" in name.lower() else 15

    # Logarithmic Slot Expectation
    s_expected_fraction = math.log(1 + a * p) / math.log(1 + a)
    expected_slots = min(total_slots * s_expected_fraction, total_slots)

    # Ratio: Deserved Slots / Actual Slots
    # If 1.0, you have exactly what you deserve. Higher = Dry, Lower = Spooned.
    safe_actual = max(actual_slots, 0.1)

    if actual_slots >= total_slots:
        ratio = actual_kc / expected_kc # Standard EHC math for finished logs
    else:
        ratio = expected_slots / safe_actual

    if ratio <= 0.5: status = "Spooned 🥄"
    elif ratio <= 0.85: status = "Wet 💧"
    elif ratio <= 1.15: status = "On-Rate 🎯"
    elif ratio <= 1.5: status = "Dry 🏜️"
    else: status = "Very Dry 💀"

    return status, ratio, expected_slots

# --- MAIN UI ---
def main():
    st.title("OSRS Clog Luck Analyzer")
    st.markdown("Comparing your KC to the **Expected KC (EKC)** and weighting it against your log progress.")

    clog_data = load_all_clog_data()

    with st.sidebar:
        st.header("Player Info")
        player_name = st.text_input("Username", value="Spencejliv")
        filter_type = st.selectbox("Category", ["All", "Boss", "Raid", "Clue"])
        analyze = st.button("Analyze Account", type="primary", use_container_width=True)

    if analyze:
        with st.spinner("Fetching Hiscores & Collection Log..."):
            kc_api = fetch_player_kc(player_name)
            clog_api = fetch_clog_slots(player_name)

        if not kc_api:
            st.error("Could not find player stats on TempleOSRS. Check the name spelling.")
            return

        # Flatten Temple Stats
        flat_kc = {str(k).lower(): v for k, v in kc_api.items()}
        if "bosses" in flat_kc and isinstance(flat_kc["bosses"], dict):
            flat_kc.update({k.lower(): v for k, v in flat_kc["bosses"].items()})

        results = []
        total_r, count = 0, 0

        for key, info in clog_data.items():
            if filter_type != "All" and info["type"] != filter_type:
                continue

            # 1. Get Actual KC
            actual_kc = flat_kc.get(key.lower(), 0)
            if actual_kc <= 0: continue

            # 2. Get Clog Data (Actual/Total)
# Check if clog_api exists; if not, use a default 1/1 dict
if clog_api and isinstance(clog_api, dict):
    clog_info = clog_api.get(info["name"].lower(), {"actual": 1, "total": 1})
else:
    clog_info = {"actual": 1, "total": 1}

            # 3. Calculate Luck
            status, ratio, exp_slots = determine_luck_v2(
                actual_kc, info["ekc"], clog_info["actual"], clog_info["total"], info["name"]
            )

            results.append({
                "Activity": info["name"],
                "Clog Progress": f"{clog_info['actual']}/{clog_info['total']}",
                "Expected Slots": round(exp_slots, 1),
                "Your KC": actual_kc,
                "Expected KC": info["ekc"],
                "Luck Ratio": ratio,
                "Status": status
            })
            total_r += ratio
            count += 1

        if results:
            df = pd.DataFrame(results).sort_values("Luck Ratio", ascending=False)

            # Using st.table for layout safety against blank screens
            st.table(df)

            st.divider()

            # Overall Logic
            avg = total_r / count
            if avg <= 0.85: overall = "Overall Spooned 🥄"
            elif avg >= 1.15: overall = "Overall Dry 🏜️"
            else: overall = "Overall On-Rate 🎯"

            c1, c2, c3 = st.columns(3)
            c1.metric("Account Luck", overall)
            c2.metric("Avg Luck Ratio", f"{avg:.2f}")
            c3.metric("Activities Analyzed", count)
        else:
            st.info("The player was found, but no KC was found for the selected categories.")

if __name__ == "__main__":
    main()
