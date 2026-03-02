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
                        if "ekc" in v and (v["ekc"] is None or (isinstance(v["ekc"], float) and math.isnan(v["ekc"]))):
                            v["ekc"] = 0.0
                        v["type"] = activity_type
                        combined[k] = v
            except Exception as e:
                st.error(f"Error reading {filename}: {e}")
    combined.update(RAIDS_DATA)
    return combined

# --- API FUNCTIONS ---
@st.cache_data(ttl=3600)
def fetch_player_data(player_name):
    # Fetching everything to ensure raids and clues are included
    url = f"https://templeosrs.com/api/player_stats.php?player={player_name}&bosses=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.json().get("data", {})
    except: return None

@st.cache_data(ttl=3600)
def fetch_temple_clog(player_name, api_keys):
    categories_str = ",".join(api_keys)
    url = f"https://templeosrs.com/api/collection-log/player_collection_log.php?player={player_name}&categories={categories_str}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.json().get("data", {})
    except: return {}

# --- HELPER: KEY NORMALIZATION ---
def norm(text):
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("_", "").replace("'", "").replace("the", "")

# --- MATH & PARSING ---
def get_clog_counts(clog_payload, boss_key, local_info):
    items_dict = clog_payload.get("items", {}) if isinstance(clog_payload, dict) else {}
    # Temple uses 'nightmare' for both Phosani and regular
    search_key = "nightmare" if "nightmare" in boss_key.lower() else boss_key.lower()
    boss_api_list = items_dict.get(search_key, [])

    if isinstance(boss_api_list, list):
        actual = sum(1 for item in boss_api_list if item.get("count", 0) > 0)
    elif isinstance(boss_api_list, dict):
        actual = boss_api_list.get("obtained", 0)
    else:
        actual = 0
    total = local_info.get("slots", 0)
    return min(actual, total), total

def determine_luck_v3(actual_kc, info, actual_slots):
    ekc, slots, kph = info.get("ekc", 0), info.get("slots", 0), info.get("kph", 1.0)
    free, mega = info.get("free_slots", 0), info.get("mega_rares", 0)

    if ekc <= 0 or actual_kc <= 0 or slots <= 0: return "Not Started", 1.0, 0.0, 0.0

    p = actual_kc / ekc
    rng_total = max(1, slots - free)
    rng_actual = max(0, actual_slots - free)
    safe_mega = min(max(0, mega), rng_total)
    normal_count = rng_total - safe_mega

    c_norm = 0.03 if safe_mega > 0 else (0.05 if info["type"] == "Clue" else 0.15)
    c_mega = 0.80

    exp_rng = (normal_count * (p**2/(p**2 + c_norm))) + (safe_mega * (p**2/(p**2 + c_mega)))
    exp_display = free + min(exp_rng, rng_total)

    ratio = (actual_kc / ekc) if actual_slots >= slots else (exp_rng / max(rng_actual, 1.0))
    spoon_points = (ratio - 1.0) * (ekc / max(kph, 0.1))

    if ratio <= 0.5: status = "Spooned 🥄"
    elif ratio <= 0.85: status = "Wet 💧"
    elif ratio <= 1.15: status = "On-Rate 🎯"
    elif ratio <= 1.5: status = "Dry 🏜️"
    else: status = "Very Dry 💀"

    return status, ratio, exp_display, spoon_points

# --- MAIN ---
def main():
    st.title("OSRS Luck & Time Analyzer")
    clog_data = load_all_clog_data()

    with st.sidebar:
        player_input = st.text_input("Username(s) - Comma separated", value="Spencejliv")
        filter_type = st.selectbox("Category", ["All", "Boss", "Raid", "Clue"])
        analyze = st.button("Analyze Account(s)", type="primary", use_container_width=True)

    if analyze:
        players = [p.strip() for p in player_input.split(",") if p.strip()]
        for player in players:
            raw_data = fetch_player_data(player)
            clog_api = fetch_temple_clog(player, list(clog_data.keys()))

            if not raw_data:
                st.error(f"Could not find data for {player}")
                continue

            # Flatten Hiscores with Normalization
            flat_kc = {}
            for folder in raw_data.values():
                if isinstance(folder, dict):
                    for k, v in folder.items(): flat_kc[norm(k)] = v

            results = []
            for key, info in clog_data.items():
                if filter_type != "All" and info["type"] != filter_type: continue

                # Get KC using normalized key matching
                actual_kc = float(flat_kc.get(norm(key), 0))
                if actual_kc == 0: actual_kc = float(flat_kc.get(norm(info["name"]), 0))

                # Combine extra modes (Challenge/Expert)
                for ck in info.get("combine_kc_keys", []):
                    actual_kc += float(flat_kc.get(norm(ck), 0))

                # Meta Clue Aggregator (3rd Age / Gilded)
                if info["type"] == "Clue" and actual_kc == 0:
                    tiers = []
                    if "shared" in key: tiers = ["beginner", "easy", "medium", "hard", "elite", "master"]
                    elif "3rd" in key or "gilded" in key: tiers, is_meta = ["hard", "elite", "master"], True

                    for t in tiers:
                        val = float(flat_kc.get(norm(f"cluescrolls{t}"), 0))
                        if "3rd" in key or "gilded" in key:
                            val *= 0.086 if t == "hard" else 0.33 if t == "elite" else 1.0
                        actual_kc += val

                if actual_kc <= 0: continue

                actual_slots, total_slots = get_clog_counts(clog_api, key, info)
                status, ratio, exp, pts = determine_luck_v3(actual_kc, info, actual_slots)

                results.append({
                    "Activity": info["name"], "Clog": f"{actual_slots}/{total_slots}",
                    "Exp": f"{exp:.2f}", "KC": f"{int(actual_kc):,}",
                    "Ratio": f"{ratio:.2f}", "Spoon Points": round(pts, 1), "Status": status
                })

            if results:
                st.subheader(f"Results for {player}")
                df = pd.DataFrame(results).sort_values("Spoon Points")
                st.table(df)

if __name__ == "__main__":
    main()
