import streamlit as st
import pandas as pd
import requests
import json
import os
import math

st.set_page_config(page_title="OSRS Clog Luck Analyzer", layout="wide")

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

# --- TIME-WEIGHTED DUAL S-CURVE MATH ---
def determine_luck_v4(actual_kc, info, actual_slots):
    expected_kc = info.get("ekc", 0)
    total_slots = info.get("slots", 0)
    free_slots = info.get("free_slots", 0)
    mega_rares = info.get("mega_rares", 0)
    kph = info.get("kph", 1.0)
    name = info.get("name", "")

    if expected_kc <= 0 or actual_kc <= 0 or total_slots <= 0:
        return "Not Started", 1.0, 0.0, 0.0

    p = actual_kc / expected_kc

    rng_total_slots = max(1, total_slots - free_slots)
    rng_actual_slots = max(0, actual_slots - free_slots)
    safe_mega_rares = min(max(0, mega_rares), rng_total_slots)
    normal_slots_count = rng_total_slots - safe_mega_rares

    # Constants for curve steepness
    c_normal = 0.03 if safe_mega_rares > 0 else (0.05 if info["type"] == "Clue" else 0.15)
    c_mega = 0.80

    # EXPONENT UPGRADE: Using p^3 makes the start much flatter (forgiving)
    # but the middle much steeper (punishing).
    s_fraction_normal = (p ** 3) / ((p ** 3) + c_normal)
    s_fraction_mega = (p ** 3) / ((p ** 3) + c_mega)

    exp_rng_slots = (normal_slots_count * s_fraction_normal) + (safe_mega_rares * s_fraction_mega)
    exp_slots_display = free_slots + min(exp_rng_slots, rng_total_slots)

    if actual_slots >= total_slots:
        ratio = actual_kc / expected_kc
    elif rng_actual_slots == 0:
        ratio = max(1.0, exp_rng_slots)
    else:
        ratio = exp_rng_slots / rng_actual_slots

    # Spoon Points calculation
    total_ehc_weight = expected_kc / max(kph, 0.1)
    spoon_points = (ratio - 1.0) * total_ehc_weight

    if ratio <= 0.5: status = "Spooned 🥄"
    elif ratio <= 0.85: status = "Wet 💧"
    elif ratio <= 1.15: status = "On-Rate 🎯"
    elif ratio <= 1.5: status = "Dry 🏜️"
    else: status = "Very Dry 💀"

    return status, ratio, exp_slots_display, spoon_points

# --- MAIN UI ---
def main():
    st.title("OSRS Time-Weighted Luck Analyzer")
    st.markdown("Math updated to **Algebraic Sigmoid (Degree 3)** for a flatter start and more aggressive late-grind scaling.")

    clog_data = load_all_clog_data()
    api_keys = list(clog_data.keys())

    with st.sidebar:
        st.header("Player Info")
        player_names_input = st.text_input("Username(s) - Comma separated", value="Spencejliv")
        filter_type = st.selectbox("Category", ["All", "Boss", "Raid", "Clue"])
        analyze = st.button("Analyze Account(s)", type="primary", use_container_width=True)

    if analyze:
        player_names = [name.strip() for name in player_names_input.split(",") if name.strip()]

        if not player_names:
            st.warning("Please enter at least one username.")
            return

        with st.spinner("Calculating outcomes..."):
            all_player_tables = {}
            summary_stats = []

            for player_name in player_names:
                kc_api = fetch_player_kc(player_name)
                clog_response = fetch_exact_temple_clog(player_name, api_keys)

                if not kc_api:
                    st.error(f"No hiscore data found for **{player_name}**.")
                    continue

                clog_api = clog_response.get("data", {}) if clog_response["success"] else {}
                flat_kc = {}
                for k, v in kc_api.items():
                    if isinstance(v, dict):
                        flat_kc.update({str(sub_k).lower(): sub_v for sub_k, sub_v in v.items()})
                    else:
                        flat_kc[str(k).lower()] = v

                results = []
                total_spoon_score = 0
                count = 0

                for key, info in clog_data.items():
                    if filter_type != "All" and info["type"] != filter_type: continue

                    kc_keys_to_try = [
                        key.lower(),
                        key.lower().replace("the_", ""),
                        info["name"].lower().replace(" ", "_"),
                        info["name"].lower().replace("'", "")
                    ]

                    if "nightmare" in key.lower():
                        kc_keys_to_try.extend(["phosani's nightmare", "phosanis nightmare", "phosani"])

                    if info.get("type") == "Clue":
                        tier = info["name"].lower().replace(" clues", "").replace(" clue", "").strip()
                        if tier:
                            kc_keys_to_try.extend([f"clue scrolls ({tier})", f"clue_{tier}", f"clues_{tier}"])

                    actual_kc = 0
                    for k in kc_keys_to_try:
                        if k in flat_kc:
                            actual_kc = int(flat_kc[k])
                            if actual_kc > 0: break

                    for combine_key in info.get("combine_kc_keys", []):
                        ck = combine_key.lower()
                        if ck in flat_kc:
                            actual_kc += int(flat_kc[ck])
                        elif ck.replace(" ", "_") in flat_kc:
                            actual_kc += int(flat_kc[ck.replace(" ", "_")])

                    if info.get("type") == "Clue" and actual_kc <= 0:
                        clue_tiers_to_sum = []
                        is_mega_meta = False
                        if "shared" in key.lower():
                            clue_tiers_to_sum = ["beginner", "easy", "medium", "hard", "elite", "master"]
                        elif "3rd" in key.lower() or "gilded" in key.lower():
                            clue_tiers_to_sum = ["hard", "elite", "master"]
                            is_mega_meta = True

                        for c_tier in clue_tiers_to_sum:
                            for variant in [f"clue scrolls ({c_tier})", f"clue_{c_tier}", f"clues_{c_tier}"]:
                                if variant in flat_kc:
                                    val = int(flat_kc[variant])
                                    if is_mega_meta:
                                        if c_tier == "hard": val *= 0.086
                                        elif c_tier == "elite": val *= 0.33
                                    actual_kc += val
                                    break

                    if actual_kc <= 0: continue

                    actual_slots, total_slots = get_clog_counts(clog_api, key, info)
                    status, ratio, exp, s_points = determine_luck_v4(actual_kc, info, actual_slots)

                    results.append({
                        "Activity": info["name"],
                        "Clog Progress": f"{actual_slots}/{total_slots}",
                        "Expected Slots": f"{exp:.2f}",
                        "Your KC": f"{actual_kc:,}",
                        "Luck Ratio": f"{ratio:.2f}",
                        "Spoon Points": int(round(s_points)),
                        "Status": status
                    })
                    total_spoon_score += s_points
                    count += 1

                if results:
                    df = pd.DataFrame(results).sort_values("Spoon Points", ascending=True)
                    all_player_tables[player_name] = df
                    summary_stats.append({
                        "Player": player_name,
                        "Spoon Score": int(round(total_spoon_score)),
                        "Status": "Legendary Spoon 🥄" if total_spoon_score < -100 else "Standard" if total_spoon_score < 100 else "Deep Sea Dry 🏜️",
                        "EHC": f"{clog_api.get('ehc', 0):.1f}"
                    })

            if summary_stats:
                st.subheader("🏆 Spoon Leaderboard")
                summary_df = pd.DataFrame(summary_stats).sort_values("Spoon Score")
                st.table(summary_df)

                tabs = st.tabs(list(all_player_tables.keys()))
                for tab, p_name in zip(tabs, all_player_tables.keys()):
                    with tab:
                        st.table(all_player_tables[p_name])

if __name__ == "__main__":
    main()
