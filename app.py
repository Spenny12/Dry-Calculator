import streamlit as st
import pandas as pd
import requests
import json
import os
import math

st.set_page_config(page_title="OSRS Luck & Time Analyzer", layout="wide")

# --- DATA & CONSTANTS ---
RAIDS_DATA = {
    "chambers_of_xeric": {
        "name": "Chambers of Xeric", "type": "Raid", "ekc": 1700, "kph": 2.0, "slots": 17, "free_slots": 0, "mega_rares": 3,
        "combine_kc_keys": ["chambers_of_xeric_challenge_mode"]
    },
    "theatre_of_blood": {
        "name": "Theatre of Blood", "type": "Raid", "ekc": 1908, "kph": 3.0, "slots": 17, "free_slots": 0, "mega_rares": 2,
        "combine_kc_keys": ["theatre_of_blood_hard_mode"]
    },
    "tombs_of_amascut": {
        "name": "Tombs of Amascut", "type": "Raid", "ekc": 1186, "kph": 1.71, "slots": 16, "free_slots": 0, "mega_rares": 2,
        "combine_kc_keys": ["tombs_of_amascut_expert"]
    }
}

def load_all_clog_data():
    combined = {}
    for filename, activity_type in [("boss_clog_data.json", "Boss"), ("clue_clog_data.json", "Clue")]:
        if os.path.exists(filename):
            try:
                with open(filename, "r") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if k.lower() in ["true", "false", "0", "1"]: continue
                        if "ekc" in v and (v["ekc"] is None or math.isnan(float(v["ekc"]))):
                            v["ekc"] = 0.0
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
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.json().get("data", {})
    except: return None

@st.cache_data(ttl=3600)
def fetch_exact_temple_clog(player_name, categories_list):
    clean_keys = [k for k in categories_list if isinstance(k, str) and k.lower() not in ['true', 'false', '0', '1']]
    categories_str = ",".join(clean_keys)
    if "nightmare" not in categories_str.lower(): categories_str += ",nightmare"

    url = f"https://templeosrs.com/api/collection-log/player_collection_log.php?player={player_name}&categories={categories_str}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return {"success": True, "data": data.get("data", data)}
    except: pass
    return {"success": False}

# --- THE PARSER ---
def get_clog_counts(clog_payload, boss_key, local_info):
    items_dict = clog_payload.get("items", {}) if isinstance(clog_payload, dict) else {}
    search_key = "nightmare" if "nightmare" in boss_key.lower() else boss_key.lower()
    boss_api_list = items_dict.get(search_key, [])

    if isinstance(boss_api_list, list):
        actual = sum(1 for item in boss_api_list if item.get("count", 0) > 0)
    elif isinstance(boss_api_list, dict):
        actual = boss_api_list.get("obtained", 0)
    else:
        actual = 0

    total = local_info.get("slots", 0)
    if total > 0 and actual > total: actual = total
    return actual, total

# --- THE SPOON MATH V9 ---
def determine_luck_v9(actual_kc, info, actual_slots):
    expected_kc = info.get("ekc", 0)
    total_slots = info.get("slots", 0)
    free_slots = info.get("free_slots", 0)
    mega_rares = info.get("mega_rares", 0)
    kph = info.get("kph", 1.0)

    if expected_kc <= 0 or actual_kc <= 0 or total_slots <= 0:
        return "Not Started", 1.0, 0.0, 0

    # RNG Isolation
    rng_total_slots = max(1, total_slots - free_slots)
    rng_actual_slots = max(0, actual_slots - free_slots)

    # 1. Forward Curve: For Displaying 'Expected Slots' only
    p = actual_kc / expected_kc
    exp_rng_total = rng_total_slots * (p ** 0.85) # Balanced power
    exp_slots_display = free_slots + min(exp_rng_total, rng_total_slots)

    # 2. Inverse Curve: How much KC is 'expected' to reach your current slots?
    # This weights the 'tapering' of the log correctly.
    progress_ratio = rng_actual_slots / rng_total_slots
    expected_kc_for_slots = expected_kc * (progress_ratio ** 1.1)

    # 3. Spoon Points = (Actual KC - Expected KC for progress) / KPH
    # This represents 'Hours Saved' (Negative) or 'Hours Wasted' (Positive)
    pts = int(round((actual_kc - expected_kc_for_slots) / max(kph, 0.1)))

    # Ratio for display
    ratio = expected_kc_for_slots / max(actual_kc, 1.0)

    # --- STATUS LOGIC TIED TO POINTS ---
    if pts <= -100: status = "Spooned 🥄"
    elif pts <= -20: status = "Wet 💧"
    elif pts >= 100: status = "Very Dry 💀"
    elif pts >= 20: status = "Dry 🏜️"
    else: status = "On-Rate 🎯"

    return status, ratio, exp_slots_display, pts

# --- MAIN UI ---
def main():
    st.title("OSRS Luck & Time Analyzer")
    st.markdown("Status is tied to **Spoon Points** (Hours Saved). Sorting by largest spoon.")

    clog_data = load_all_clog_data()
    api_keys = list(clog_data.keys())

    with st.sidebar:
        st.header("Player Info")
        player_names_input = st.text_input("Username(s)", value="Spencejliv")
        filter_type = st.selectbox("Category", ["All", "Boss", "Raid", "Clue"])
        analyze = st.button("Analyze Account(s)", type="primary", use_container_width=True)

    if analyze:
        player_names = [name.strip() for name in player_names_input.split(",") if name.strip()]
        if not player_names: return

        with st.spinner("Analyzing grinds..."):
            all_player_tables = {}
            summary_stats = []

            for player_name in player_names:
                kc_api = fetch_player_kc(player_name)
                clog_response = fetch_exact_temple_clog(player_name, api_keys)
                if not kc_api: continue

                clog_api = clog_response.get("data", {}) if clog_response["success"] else {}
                flat_kc = {}
                for k, v in kc_api.items():
                    if isinstance(v, dict):
                        flat_kc.update({str(sub_k).lower(): sub_v for sub_k, sub_v in v.items()})
                    else:
                        flat_kc[str(k).lower()] = v

                results = []
                total_spoon_score = 0

                for key, info in clog_data.items():
                    if filter_type != "All" and info["type"] != filter_type: continue

                    # Name matching variants
                    kc_keys_to_try = [
                        key.lower(), key.lower().replace("the_", ""),
                        info["name"].lower().replace(" ", "_"),
                        info["name"].lower().replace("'", ""),
                        "colosseum" if "colosseum" in key.lower() else ""
                    ]

                    actual_kc = 0
                    for k in kc_keys_to_try:
                        if k and k in flat_kc:
                            actual_kc = int(flat_kc[k]); break

                    # ADDITIVE KC FIX: Nightmare + Phosani
                    if "nightmare" in key.lower():
                        for pk in ["phosani's nightmare", "phosanis nightmare", "phosani"]:
                            if pk in flat_kc: actual_kc += int(flat_kc[pk]); break

                    for ck in info.get("combine_kc_keys", []):
                        ck_low = ck.lower()
                        if ck_low in flat_kc: actual_kc += int(flat_kc[ck_low])
                        elif ck_low.replace(" ", "_") in flat_kc: actual_kc += int(flat_kc[ck_low.replace(" ", "_")])

                    if actual_kc <= 0: continue

                    actual_slots, total_slots = get_clog_counts(clog_api, key, info)
                    status, ratio, exp, pts = determine_luck_v9(actual_kc, info, actual_slots)

                    results.append({
                        "Activity": info["name"],
                        "Clog": f"{actual_slots}/{total_slots}",
                        "Expected": f"{exp:.2f}",
                        "KC": f"{actual_kc:,}",
                        "Spoon Points": pts,
                        "Status": status
                    })
                    total_spoon_score += pts

                if results:
                    df = pd.DataFrame(results).sort_values("Spoon Points", ascending=True)
                    all_player_tables[player_name] = df
                    summary_stats.append({
                        "Player": player_name,
                        "Total Spoon Score": int(round(total_spoon_score)),
                        "EHC": f"{clog_api.get('ehc', 0):.1f}"
                    })

            if summary_stats:
                st.subheader("🏆 Leaderboard")
                st.table(pd.DataFrame(summary_stats).sort_values("Total Spoon Score"))

                tabs = st.tabs(list(all_player_tables.keys()))
                for tab, p_name in zip(tabs, all_player_tables.keys()):
                    with tab:
                        st.table(all_player_tables[p_name])

if __name__ == "__main__":
    main()
