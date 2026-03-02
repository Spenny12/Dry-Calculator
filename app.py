import streamlit as st
import pandas as pd
import requests
import json
import os
import math

st.set_page_config(page_title="Chungies Spoon Calc!!!!!!!!!!", layout="wide")

# --- DATA & CONSTANTS ---
RAIDS_DATA = {
    "chambers_of_xeric": {
        "name": "Chambers of Xeric", "type": "Raid", "ekc": 1700, "kph": 2.0, "slots": 18, "free_slots": 2, "mega_rares": 4,
        "combine_kc_keys": ["chambers_of_xeric_challenge_mode"]
    },
    "theatre_of_blood": {
        "name": "Theatre of Blood", "type": "Raid", "ekc": 1908, "kph": 3.0, "slots": 12, "free_slots": 1, "mega_rares": 2,
        "combine_kc_keys": ["theatre_of_blood_hard_mode"]
    },
    "tombs_of_amascut": {
        "name": "Tombs of Amascut", "type": "Raid", "ekc": 1186, "kph": 1.71, "slots": 14, "free_slots": 1, "mega_rares": 2,
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
                        if "ekc" in v and (v["ekc"] is None or (isinstance(v["ekc"], float) and math.isnan(v["ekc"]))):
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
    # Ensure DT2 and Nightmare are requested correctly
    if "nightmare" not in categories_str.lower(): categories_str += ",the_nightmare"

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

    # Try the exact key from your JSON first
    boss_api_list = items_dict.get(boss_key, [])

    # Common nightmare and DT2 Fallbacks
    if not boss_api_list:
        if "nightmare" in boss_key: boss_api_list = items_dict.get("the_nightmare", items_dict.get("nightmare", []))
        elif "sucellus" in boss_key: boss_api_list = items_dict.get("duke_sucellus", [])
        elif "whisperer" in boss_key: boss_api_list = items_dict.get("the_whisperer", [])
        elif "leviathan" in boss_key: boss_api_list = items_dict.get("the_leviathan", [])

    if isinstance(boss_api_list, list):
        actual = sum(1 for item in boss_api_list if item.get("count", 0) > 0)
    elif isinstance(boss_api_list, dict):
        actual = boss_api_list.get("obtained", 0)
    else:
        actual = 0

    total = local_info.get("slots", 0)
    if total > 0 and actual > total: actual = total
    return actual, total

# --- THE SPOON MATH V10 (STRICT POWER CURVE) ---
def determine_luck_v10(actual_kc, info, actual_slots):
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
    safe_mega_rares = min(max(0, mega_rares), rng_total_slots)
    normal_rng_slots = rng_total_slots - safe_mega_rares

    # Strict Power Curve
    p = actual_kc / expected_kc
    exp_normal = normal_rng_slots * (p ** 0.5)
    exp_mega = safe_mega_rares * (p ** 2.5)

    exp_rng_total = min(exp_normal + exp_mega, rng_total_slots)
    exp_slots_display = free_slots + exp_rng_total

    # Inverse Curve for Score
    progress_ratio = rng_actual_slots / rng_total_slots
    expected_kc_for_progress = expected_kc * (progress_ratio ** 2.0)

    pts = int(round((actual_kc - expected_kc_for_progress) / max(kph, 0.1)))
    display_ratio = expected_kc_for_progress / max(actual_kc, 1.0)

    # Status Mapping (+/- 10 threshold)
    if pts <= -25: status = "Spooned 🥄"
    elif pts <= -10: status = "Wet 💧"
    elif pts >= 25: status = "Very Dry 💀"
    elif pts >= 10: status = "Dry 🏜️"
    else: status = "On-Rate 🎯"

    return status, display_ratio, exp_slots_display, pts

# --- MAIN UI ---
def main():
    st.title("Spoon Calc")
    st.markdown("Readme coming soon. Lower the spoon score, the more spooned")

    clog_data = load_all_clog_data()
    api_keys = list(clog_data.keys())

    with st.sidebar:
        st.header("Player Info")
        player_names_input = st.text_input("Username(s)", value="Spencejliv")
        filter_type = st.selectbox("Category", ["All", "Boss", "Raid", "Clue"])
        analyze = st.button("ARun", type="primary", use_container_width=True)

    if analyze:
        player_names = [name.strip() for name in player_names_input.split(",") if name.strip()]
        if not player_names: return

        with st.spinner("Hunting for DT2 Bosses..."):
            all_player_tables = {}
            summary_stats = []

            for player_name in player_names:
                kc_api = fetch_player_kc(player_name)
                clog_response = fetch_exact_temple_clog(player_name, api_keys)
                if not kc_api: continue

                clog_api = clog_response.get("data", {}) if clog_response["success"] else {}
                # Flatten keys to lowercase for matching
                flat_kc = {str(k).lower(): v for k, v in kc_api.items()}

                results = []
                total_spoon_score = 0

                for key, info in clog_data.items():
                    if filter_type != "All" and info["type"] != filter_type: continue

                    # AGGRESSIVE KC MATCHING FOR DT2
                    clean_key = key.lower()
                    kc_keys_to_try = [
                        clean_key,
                        clean_key.replace("the_", ""),
                        clean_key.replace("_", " "),
                        info["name"].lower(),
                        info["name"].lower().replace(" ", "_"),
                        "duke sucellus" if "sucellus" in clean_key else "",
                        "the whisperer" if "whisperer" in clean_key else "",
                        "the leviathan" if "leviathan" in clean_key else ""
                    ]

                    actual_kc = 0
                    for k in kc_keys_to_try:
                        if k and k in flat_kc:
                            actual_kc = int(flat_kc[k])
                            if actual_kc > 0: break

                    # Nightmare Fix
                    if "nightmare" in clean_key:
                        for pk in ["phosani's nightmare", "phosani", "phosanis nightmare"]:
                            if pk in flat_kc: actual_kc += int(flat_kc[pk]); break

                    # Raids/Modes Fix
                    for ck in info.get("combine_kc_keys", []):
                        ck_low = ck.lower()
                        if ck_low in flat_kc: actual_kc += int(flat_kc[ck_low])
                        elif ck_low.replace(" ", "_") in flat_kc: actual_kc += int(flat_kc[ck_low.replace(" ", "_")])

                    if actual_kc <= 0: continue

                    actual_slots, total_slots = get_clog_counts(clog_api, key, info)
                    status, ratio, exp, pts = determine_luck_v10(actual_kc, info, actual_slots)

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
                        "EHC": f"{clog_api.get('ehc', 0):.1f}" if isinstance(clog_api, dict) else "0.0"
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
