import streamlit as st
import pandas as pd
import requests
import json
import os
import math

# 1. Page Config MUST be the first Streamlit command
st.set_page_config(page_title="OSRS Clog Luck Analyzer", layout="wide")

# --- DATA & CONSTANTS ---
RAIDS_DATA = {
    "chambers_of_xeric": {"name": "Chambers of Xeric", "type": "Raid", "ekc": 1700, "kph": 2.0},
    "theatre_of_blood": {"name": "Theatre of Blood", "type": "Raid", "ekc": 1908, "kph": 3.0},
    "tombs_of_amascut": {"name": "Tombs of Amascut", "type": "Raid", "ekc": 1186, "kph": 1.71}
}

@st.cache_data
def load_all_clog_data():
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
    url = f"https://templeosrs.com/api/player_stats.php?player={player_name}&bosses=1"
    try:
        r = requests.get(url, timeout=10)
        return r.json().get("data", {})
    except: return None

@st.cache_data(ttl=3600)
def fetch_clog_slots(player_name):
    url = f"https://api.collectionlog.net/collectionlog/user/{player_name}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200: return None
        data = r.json()
        clog_stats = {}
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

# --- LOGARITHMIC MATH ---
def determine_progress_luck(actual_kc, expected_kc, actual_slots, total_slots, name=""):
    if actual_kc <= 0 or expected_kc <= 0 or total_slots <= 0:
        return "Not Started", 1.0, 0.0

    p = actual_kc / expected_kc
    a = 2 if "barrows" in name.lower() else 15
    s = math.log(1 + a * p) / math.log(1 + a)

    exp_slots = min(total_slots * s, total_slots)

    # Avoid 0 division if player has 0 slots
    safe_actual = max(actual_slots, 0.1)

    if actual_slots >= total_slots:
        ratio = actual_kc / expected_kc
    else:
        ratio = exp_slots / safe_actual

    if ratio <= 0.5: status = "Spooned 🥄"
    elif ratio <= 0.9: status = "Wet 💧"
    elif ratio <= 1.1: status = "On-Rate 🎯"
    elif ratio <= 1.5: status = "Dry 🏜️"
    else: status = "Very Dry 💀"
    return status, ratio, exp_slots

# --- UI RENDERING ---
def main():
    st.title("OSRS Clog Luck Analyzer")

    clog_data = load_all_clog_data()

    with st.sidebar:
        st.header("Settings")
        player_name = st.text_input("Username", value="Spencejliv")
        filter_type = st.selectbox("Category", ["All", "Boss", "Raid", "Clue"])
        analyze = st.button("Analyze", type="primary", use_container_width=True)

    if analyze:
        with st.spinner("Fetching data..."):
            kc_data = fetch_player_kc(player_name)
            clog_api = fetch_clog_slots(player_name)

        if not kc_data:
            st.error("No hiscore data found. Is the name correct?")
            return

        # Flatten TempleOSRS data
        flat_kc = {str(k).lower(): v for k, v in kc_data.items()}
        if "bosses" in flat_kc and isinstance(flat_kc["bosses"], dict):
            flat_kc.update({k.lower(): v for k, v in flat_kc["bosses"].items()})

        results = []
        total_r, count = 0, 0

        for key, info in clog_data.items():
            if filter_type != "All" and info["type"] != filter_type:
                continue

            actual_kc = flat_kc.get(key.lower(), 0)
            if actual_kc <= 0: continue

            clog_info = clog_api.get(info["name"].lower(), {"actual": 1, "total": 1}) if clog_api else {"actual": 1, "total": 1}

            status, ratio, exp_s = determine_progress_luck(
                actual_kc, info["ekc"], clog_info["actual"], clog_info["total"], info["name"]
            )

            results.append({
                "Activity": info["name"],
                "Clog": f"{clog_info['actual']}/{clog_info['total']}",
                "Expected Slots": round(exp_s, 1),
                "KC": actual_kc,
                "Ratio": ratio,
                "Status": status
            })
            total_r += ratio
            count += 1

        if results:
            df = pd.DataFrame(results).sort_values("Ratio", ascending=False)
            st.table(df) # Using st.table for maximum stability

            st.divider()
            avg = total_r / count
            st.metric("Overall Luck", "Spooned 🥄" if avg < 0.9 else "Dry 🏜️" if avg > 1.1 else "On-Rate 🎯", f"{avg:.2f} Ratio")
        else:
            st.warning("No matching activity data found for this player.")

if __name__ == "__main__":
    main()
