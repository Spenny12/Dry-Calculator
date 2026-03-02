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
def fetch_player_data(player_name):
    url = f"https://templeosrs.com/api/player_stats.php?player={player_name}&bosses=1"
    try:
        r = requests.get(url, timeout=15)
        return r.json().get("data", {})
    except Exception as e:
        st.error(f"Hiscore API Error: {e}")
        return None

@st.cache_data(ttl=600)
def fetch_temple_clog(player_name):
    # Using your specific requested API structure
    url = f"https://templeosrs.com/api/collection-log/player_collection_log.php?player={player_name}&categories=bosses,raids,clues"
    try:
        r = requests.get(url, timeout=15)
        return r.json().get("data", {})
    except Exception as e:
        st.error(f"Collection Log API Error: {e}")
        return {}

# --- HELPER: KEY NORMALIZATION ---
def norm(text):
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("_", "").replace(":", "").replace("'", "").replace("the", "")

# --- MATH ENGINE ---
def determine_luck_v3(actual_kc, info, actual_slots):
    ekc, slots, kph = info.get("ekc", 0), info.get("slots", 0), info.get("kph", 1.0)
    free, mega = info.get("free_slots", 0), info.get("mega_rares", 0)

    if ekc <= 0 or actual_kc <= 0 or slots <= 0: return "Not Started", 1.0, 0.0, 0.0

    p = actual_kc / ekc
    rng_total = max(1, slots - free)
    rng_actual = max(0, actual_slots - free)
    safe_mega = min(max(0, mega), rng_total)
    normal_count = rng_total - safe_mega

    # Dual S-Curve
    c_norm = 0.03 if safe_mega > 0 else (0.05 if info["type"] == "Clue" else 0.15)
    c_mega = 0.80

    s_frac_normal = (p**2 / (p**2 + c_norm))
    s_frac_mega = (p**2 / (p**2 + c_mega))

    exp_rng = (normal_count * s_frac_normal) + (safe_mega * s_frac_mega)
    exp_display = free + min(exp_rng, rng_total)

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
            all_player_results = {}
            summary_list = []

            with st.spinner("Analyzing data..."):
                for player in players:
                    raw_kc_data = fetch_player_data(player)
                    clog_api = fetch_temple_clog(player)

                    if not raw_kc_data: continue

                    # Flatten Hiscores with absolute normalization
                    flat_kc = {}
                    for folder in raw_kc_data.values():
                        if isinstance(folder, dict):
                            for k, v in folder.items(): flat_kc[norm(k)] = v
                        else:
                            flat_kc[norm(folder)] = folder

                    # Gather item lists from Temple for matching
                    items_dict = clog_api.get("items", {})

                    player_results = []
                    total_pts = 0

                    for key, info in clog_data.items():
                        if filter_type != "All" and info["type"] != filter_type: continue

                        # KC MATCHING: Search by JSON Key, then by Human Name
                        actual_kc = float(flat_kc.get(norm(key), 0))
                        if actual_kc == 0:
                            actual_kc = float(flat_kc.get(norm(info["name"]), 0))

                        # COMBINE EXTRA MODES (Challenge/Expert)
                        for ck in info.get("combine_kc_keys", []):
                            actual_kc += float(flat_kc.get(norm(ck), 0))

                        # META CLUE AGGREGATOR
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

                        # SLOT MATCHING: Loop through Temple categories to find the matching boss name
                        actual_slots = 0
                        found_match = False
                        for api_cat_name, api_item_list in items_dict.items():
                            if norm(api_cat_name) == norm(info["name"]) or norm(api_cat_name) == norm(key):
                                if isinstance(api_item_list, list):
                                    actual_slots = sum(1 for item in api_item_list if item.get("count", 0) > 0)
                                    found_match = True
                                    break

                        # Final fallback for cases like Nightmare where naming is complex
                        if not found_match and "nightmare" in key.lower():
                            api_list = items_dict.get("nightmare", [])
                            if isinstance(api_list, list):
                                actual_slots = sum(1 for item in api_list if item.get("count", 0) > 0)

                        status, ratio, exp, pts = determine_luck_v3(actual_kc, info, actual_slots)

                        player_results.append({
                            "Activity": info["name"], "Clog": f"{actual_slots}/{info['slots']}",
                            "Exp": f"{exp:.2f}", "KC": f"{int(actual_kc):,}",
                            "Ratio": f"{ratio:.2f}", "Spoon Points": round(pts, 1), "Status": status
                        })
                        total_pts += pts

                    if player_results:
                        df = pd.DataFrame(player_results).sort_values("Spoon Points")
                        all_player_results[player] = df
                        summary_list.append({
                            "Player": player, "Spoon Score": round(total_pts, 1),
                            "EHC": f"{clog_api.get('ehc', 0):.1f}"
                        })

            if summary_list:
                st.subheader("🏆 Leaderboard")
                st.table(pd.DataFrame(summary_list).sort_values("Spoon Score"))

                tabs = st.tabs(list(all_player_results.keys()))
                for tab, p_name in zip(tabs, all_player_results.keys()):
                    with tab:
                        st.table(all_player_results[p_name])
            else:
                st.warning("No data found. Check that usernames are spelled correctly.")

        except Exception:
            st.error("Traceback error detected:")
            st.code(traceback.format_exc())

if __name__ == "__main__":
    main()
