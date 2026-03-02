import streamlit as st
import pandas as pd
import requests
import json
import os
import math
import traceback

st.set_page_config(page_title="OSRS Luck & Time Analyzer", layout="wide")

# --- DATA & CONSTANTS ---
RAIDS_DATA = {
    "chambers_of_xeric": {
        "name": "Chambers of Xeric", "type": "Raid", "ekc": 1700, "kph": 2.0, "slots": 17, "free_slots": 0, "mega_rares": 3,
        "combine_kc_keys": ["Chambers of Xeric Challenge Mode"]
    },
    "theatre_of_blood": {
        "name": "Theatre of Blood", "type": "Raid", "ekc": 1908, "kph": 3.0, "slots": 17, "free_slots": 0, "mega_rares": 2,
        "combine_kc_keys": ["Theatre of Blood Hard Mode"]
    },
    "tombs_of_amascut": {
        "name": "Tombs of Amascut", "type": "Raid", "ekc": 1186, "kph": 1.71, "slots": 16, "free_slots": 0, "mega_rares": 2,
        "combine_kc_keys": ["Tombs of Amascut: Expert Mode"]
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
@st.cache_data(ttl=600)
def fetch_player_kc(player_name):
    url = f"https://templeosrs.com/api/player_stats.php?player={player_name}&bosses=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=10) # 10s timeout to prevent hanging
        return r.json().get("data", {})
    except Exception as e:
        st.error(f"Hiscore API Error: {e}")
        return None

@st.cache_data(ttl=600)
def fetch_temple_clog(player_name):
    # Using the exact category structure you specified
    url = f"https://templeosrs.com/api/collection-log/player_collection_log.php?player={player_name}&categories=bosses,raids,clues"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.json().get("data", {})
    except Exception as e:
        st.error(f"Collection Log API Error: {e}")
        return {}

# --- HELPER: KEY NORMALIZATION ---
def norm(text):
    if not text: return ""
    # Only alphanumeric for matching
    return "".join(filter(str.isalnum, str(text).lower()))

# --- MATH ENGINE ---
def determine_luck_v3(actual_kc, info, actual_slots):
    ekc, slots, kph = info.get("ekc", 0), info.get("slots", 0), info.get("kph", 1.0)
    free, mega = info.get("free_slots", 0), info.get("mega_rares", 0)

    if ekc <= 0 or actual_kc <= 0 or slots <= 0:
        return "Not Started", 1.0, 0.0, 0.0

    p = actual_kc / ekc
    rng_total = max(1, slots - free)
    rng_actual = max(0, actual_slots - free)
    safe_mega = min(max(0, mega), rng_total)
    normal_count = rng_total - safe_mega

    # Dual S-Curve (c determines steepness/speed)
    c_normal = 0.03 if safe_mega > 0 else (0.05 if info["type"] == "Clue" else 0.15)
    c_mega = 0.80

    s_frac_normal = (p**2 / (p**2 + c_normal))
    s_frac_mega = (p**2 / (p**2 + c_mega))

    exp_rng = (normal_count * s_frac_normal) + (safe_mega * s_frac_mega)
    exp_display = free + min(exp_rng, rng_total)

    # Ratio calculation
    if actual_slots >= slots:
        ratio = actual_kc / ekc
    elif rng_actual == 0:
        ratio = max(1.0, exp_rng)
    else:
        ratio = exp_rng / rng_actual

    total_ehc_weight = ekc / max(kph, 0.1)
    spoon_points = (ratio - 1.0) * total_ehc_weight

    if ratio <= 0.5: status = "Spooned 🥄"
    elif ratio <= 0.85: status = "Wet 💧"
    elif ratio <= 1.15: status = "On-Rate 🎯"
    elif ratio <= 1.5: status = "Dry 🏜️"
    else: status = "Very Dry 💀"

    return status, ratio, exp_display, spoon_points

# --- MAIN UI ---
def main():
    st.title("OSRS Luck & Time Analyzer")
    clog_data = load_all_clog_data()

    with st.sidebar:
        st.header("Settings")
        player_input = st.text_input("Username(s) - Comma separated", value="Spencejliv")
        filter_type = st.selectbox("Category Filter", ["All", "Boss", "Raid", "Clue"])
        analyze = st.button("Analyze Account(s)", type="primary", use_container_width=True)

    if analyze:
        try:
            players = [p.strip() for p in player_input.split(",") if p.strip()]
            for player in players:
                with st.spinner(f"Analyzing {player}..."):
                    kc_api = fetch_player_kc(player)
                    clog_api = fetch_temple_clog(player)

                    if not kc_api: continue

                    # Flatten Hiscores so Clues/Raids are found
                    flat_kc = {}
                    for folder in kc_api.values():
                        if isinstance(folder, dict):
                            for k, v in folder.items(): flat_kc[norm(k)] = v
                        elif isinstance(folder, (int, float)):
                            pass # Top-level meta data skip

                    items_dict = clog_api.get("items", {})
                    # Map Temple keys to normalized versions for quick lookup
                    norm_clog_map = {norm(k): k for k in items_dict.keys()}

                    results = []
                    for key, info in clog_data.items():
                        if filter_type != "All" and info["type"] != filter_type: continue

                        # 1. KC Match
                        actual_kc = float(flat_kc.get(norm(key), 0))
                        if actual_kc == 0: actual_kc = float(flat_kc.get(norm(info["name"]), 0))

                        # Add Extra Modes (Expert/Hard/Challenge)
                        for ck in info.get("combine_kc_keys", []):
                            actual_kc += float(flat_kc.get(norm(ck), 0))

                        # Meta Clue Aggregate (3rd Age/Gilded)
                        if info["type"] == "Clue" and actual_kc == 0:
                            tiers = []
                            if "shared" in key: tiers = ["beginner", "easy", "medium", "hard", "elite", "master"]
                            elif "3rd" in key or "gilded" in key: tiers = ["hard", "elite", "master"]
                            for t in tiers:
                                val = float(flat_kc.get(norm(f"cluescrolls{t}"), 0))
                                if "3rd" in key or "gilded" in key:
                                    val *= 0.086 if t == "hard" else 0.33 if t == "elite" else 1.0
                                actual_kc += val

                        if actual_kc <= 0: continue

                        # 2. Clog Progress Match
                        actual_slots = 0
                        # Check JSON key first, then human name
                        t_key = norm_clog_map.get(norm(key))
                        if not t_key: t_key = norm_clog_map.get(norm(info["name"]))

                        if t_key:
                            api_list = items_dict.get(t_key, [])
                            if isinstance(api_list, list):
                                actual_slots = sum(1 for item in api_list if item.get("count", 0) > 0)

                        status, ratio, exp, pts = determine_luck_v3(actual_kc, info, actual_slots)
                        results.append({
                            "Activity": info["name"], "Clog": f"{actual_slots}/{info['slots']}",
                            "Exp": f"{exp:.2f}", "KC": f"{int(actual_kc):,}",
                            "Ratio": f"{ratio:.2f}", "Spoon Points": round(pts, 1), "Status": status
                        })

                    if results:
                        st.subheader(f"Results for {player}")
                        st.table(pd.DataFrame(results).sort_values("Spoon Points"))
                    else:
                        st.info(f"No active data found for {player}.")

        except Exception:
            st.error("The script encountered an error. See details below:")
            st.code(traceback.format_exc())

if __name__ == "__main__":
    main()
