import streamlit as st
import pandas as pd
import requests
import json
import os
import math

# 1. Page Config (Must be the first command)
st.set_page_config(page_title="OSRS Clog Luck Analyzer", layout="wide")

# --- DATA & CONSTANTS ---
# Slots added here so raids work instantly
RAIDS_DATA = {
    "chambers_of_xeric": {"name": "Chambers of Xeric", "type": "Raid", "ekc": 1700, "kph": 2.0, "slots": 17},
    "theatre_of_blood": {"name": "Theatre of Blood", "type": "Raid", "ekc": 1908, "kph": 3.0, "slots": 7},
    "tombs_of_amascut": {"name": "Tombs of Amascut", "type": "Raid", "ekc": 1186, "kph": 1.71, "slots": 8}
}

# No @st.cache_data here so your JSON edits show up immediately on refresh!
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

# --- TEMPLEOSRS API FUNCTIONS ---
@st.cache_data(ttl=3600)
def fetch_player_kc(player_name):
    url = f"https://templeosrs.com/api/player_stats.php?player={player_name}&bosses=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.json().get("data", {})
    except: return None

@st.cache_data(ttl=3600)
def fetch_exact_temple_clog(player_name, categories_list):
    clean_keys = [k for k in categories_list if isinstance(k, str) and k.lower() not in ['true', 'false', '0', '1']]
    categories_str = ",".join(clean_keys)
    url = f"https://templeosrs.com/api/collection-log/player_collection_log.php?player={player_name}&categories={categories_str}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return {"success": True, "data": data.get("data", data)}
    except: pass
    return {"success": False}

# --- PARSERS ---
def get_clog_counts(clog_payload, boss_key, local_info):
    items_dict = clog_payload.get("items", {}) if isinstance(clog_payload, dict) else {}
    boss_data = items_dict.get(boss_key.lower())

    if isinstance(boss_data, list):
        actual = len(boss_data)
    elif isinstance(boss_data, dict):
        actual = boss_data.get("obtained", 0)
    else:
        actual = 0

    total = local_info.get("slots", 0)
    return actual, total

def determine_luck_v2(actual_kc, expected_kc, actual_slots, total_slots, name=""):
    if actual_kc <= 0 or expected_kc <= 0 or total_slots <= 0:
        return "Not Started", 1.0, 0.0

    p = actual_kc / expected_kc
    a = 2 if "barrows" in name.lower() or "clue" in name.lower() else 15
    s = math.log(1 + a * p) / math.log(1 + a)
    exp_slots = min(total_slots * s, total_slots)

    ratio = exp_slots / max(actual_slots, 0.1)
    if actual_slots >= total_slots: ratio = actual_kc / expected_kc

    if ratio <= 0.5: status = "Spooned 🥄"
    elif ratio <= 0.85: status = "Wet 💧"
    elif ratio <= 1.15: status = "On-Rate 🎯"
    elif ratio <= 1.5: status = "Dry 🏜️"
    else: status = "Very Dry 💀"

    return status, ratio, exp_slots

# --- MAIN UI ---
def main():
    st.title("OSRS Clog Luck Analyzer")
    st.markdown("Comparing KC to Expected KC (EKC) weighted by Log Progress.")

    clog_data = load_all_clog_data()
    api_keys = list(clog_data.keys())

    with st.sidebar:
        st.header("Player Info")
        player_name = st.text_input("Username", value="Spencejliv")
        filter_type = st.selectbox("Category", ["All", "Boss", "Raid", "Clue"])
        analyze = st.button("Analyze Account", type="primary", use_container_width=True)

    if analyze:
        with st.spinner("Fetching data..."):
            kc_api = fetch_player_kc(player_name)
            clog_response = fetch_exact_temple_clog(player_name, api_keys)

        if not kc_api:
            st.error("No hiscore data found.")
            return

        clog_api = clog_response.get("data", {}) if clog_response["success"] else {}
        flat_kc = {str(k).lower(): v for k, v in kc_api.items()}
        if "bosses" in flat_kc and isinstance(flat_kc["bosses"], dict):
            flat_kc.update({k.lower(): v for k, v in flat_kc["bosses"].items()})

        results = []
        total_r, count = 0, 0

        for key, info in clog_data.items():
            if filter_type != "All" and info["type"] != filter_type:
                continue

            # --- SMARTER KC LOOKUP ---
            # Checks for variations like 'the_nightmare' vs 'nightmare'
            kc_keys_to_try = [
                key.lower(),
                key.lower().replace("the_", ""),
                info["name"].lower().replace(" ", "_"),
                info["name"].lower().replace("'", "")
            ]

            actual_kc = 0
            for k in kc_keys_to_try:
                if k in flat_kc:
                    actual_kc = int(flat_kc[k])
                    if actual_kc > 0: break

            if actual_kc <= 0: continue

            actual_slots, total_slots = get_clog_counts(clog_api, key, info)
            missing_total = (total_slots == 0)
            if missing_total: total_slots = max(actual_slots, 1)

            status, ratio, exp_slots = determine_luck_v2(actual_kc, info["ekc"], actual_slots, total_slots, info["name"])

            # --- REFINED ALIGNMENT FORMATTING ---
            results.append({
                "Activity": info["name"],
                "Clog Progress": f"{actual_slots}/{total_slots}" if not missing_total else f"{actual_slots}/?",
                "Expected Slots": f"{exp_slots:.1f}" if not missing_total else "⚠️ Set slots in JSON",
                "Your KC": f"{actual_kc:,}",
                "Luck Ratio": f"{ratio:.2f}" if not missing_total else "N/A",
                "Status": status if not missing_total else "N/A"
            })

            if not missing_total:
                total_r += ratio
                count += 1

        if results:
            df = pd.DataFrame(results).sort_values("Luck Ratio", ascending=False)
            st.table(df)
            st.divider()

            if count > 0:
                avg = total_r / count
                overall = "Overall Spooned 🥄" if avg <= 0.85 else "Overall Dry 🏜️" if avg >= 1.15 else "Overall On-Rate 🎯"
                ehc_value = clog_api.get('ehc', 0) if isinstance(clog_api, dict) else 0

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Account Luck", overall)
                c2.metric("Avg Luck Ratio", f"{avg:.2f}")
                c3.metric("Activities Analyzed", count)
                c4.metric("Temple EHC", f"{ehc_value:,.1f} hrs")
        else:
            st.info("No matching data found.")

if __name__ == "__main__":
    main()
