import streamlit as st
import pandas as pd
import requests
import json
import os
import math

st.set_page_config(page_title="OSRS Clog Luck Analyzer", layout="wide")

# --- DATA & CONSTANTS ---
RAIDS_DATA = {
    "chambers_of_xeric": {"name": "Chambers of Xeric", "type": "Raid", "ekc": 1700, "kph": 2.0, "slots": 17},
    "theatre_of_blood": {"name": "Theatre of Blood", "type": "Raid", "ekc": 1908, "kph": 3.0, "slots": 7},
    "tombs_of_amascut": {"name": "Tombs of Amascut", "type": "Raid", "ekc": 1186, "kph": 1.71, "slots": 8}
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

# --- THE S-CURVE MATH ---
def determine_luck_v2(actual_kc, expected_kc, actual_slots, total_slots, name=""):
    if expected_kc is None or expected_kc <= 0 or actual_kc <= 0 or total_slots <= 0:
        return "Not Started", 1.0, 0.0

    p = actual_kc / expected_kc

    # 'c' controls the curve. 0.05 is faster (Clues/Barrows). 0.15 is slower (Bosses).
    c = 0.05 if "barrows" in name.lower() or "clue" in name.lower() else 0.15

    # The Algebraic S-Curve
    s_fraction = (p ** 2) / ((p ** 2) + c)
    exp_slots = min(total_slots * s_fraction, total_slots)

    # The True Ratio Fix
    if actual_slots >= total_slots:
        ratio = actual_kc / expected_kc
    elif actual_slots == 0:
        # If you have 0 slots, you get a free pass if expected is low, but punished if expected is high.
        ratio = max(1.0, exp_slots)
    else:
        ratio = exp_slots / actual_slots

    if ratio <= 0.5: status = "Spooned 🥄"
    elif ratio <= 0.85: status = "Wet 💧"
    elif ratio <= 1.15: status = "On-Rate 🎯"
    elif ratio <= 1.5: status = "Dry 🏜️"
    else: status = "Very Dry 💀"

    return status, ratio, exp_slots

# --- MAIN UI ---
def main():
    st.title("OSRS Clog Luck Analyzer")
    st.markdown("Comparing KC to Expected KC (EKC) using an S-Curve for realistic log progress. Compare multiple players at once!")

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

        with st.spinner("Fetching data for all players..."):
            all_player_tables = {}
            summary_stats = []

            for player_name in player_names:
                kc_api = fetch_player_kc(player_name)
                clog_response = fetch_exact_temple_clog(player_name, api_keys)

                if not kc_api:
                    st.error(f"No hiscore data found for **{player_name}**.")
                    continue

                clog_api = clog_response.get("data", {}) if clog_response["success"] else {}
                flat_kc = {str(k).lower(): v for k, v in kc_api.items()}

                if "bosses" in flat_kc and isinstance(flat_kc["bosses"], dict):
                    flat_kc.update({k.lower(): v for k, v in flat_kc["bosses"].items()})

                results = []
                total_r, count = 0, 0

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

                    results.append({
                        "Activity": info["name"],
                        "Clog Progress": f"{actual_slots}/{total_slots}" if not missing_total else f"{actual_slots}/?",
                        "Expected Slots": f"{exp_slots:.2f}" if not missing_total else "⚠️ Check JSON",
                        "Your KC": f"{actual_kc:,}",
                        "Luck Ratio": f"{ratio:.2f}" if not missing_total else "N/A",
                        "Status": status if not missing_total else "N/A"
                    })

                    if not missing_total:
                        total_r += ratio
                        count += 1

                if results:
                    df = pd.DataFrame(results).sort_values("Luck Ratio", ascending=False)
                    all_player_tables[player_name] = df

                    avg = total_r / count if count > 0 else 0
                    if avg <= 0.85: overall = "Spooned 🥄"
                    elif avg >= 1.15: overall = "Dry 🏜️"
                    else: overall = "On-Rate 🎯"

                    ehc_val = clog_api.get('ehc', 0) if isinstance(clog_api, dict) else 0

                    summary_stats.append({
                        "Player": player_name,
                        "Avg Luck Ratio": round(avg, 2),
                        "Account Luck": overall,
                        "Temple EHC": f"{ehc_val:,.1f}",
                        "Activities Analyzed": count,
                        "_raw_ehc": ehc_val,
                        "_raw_avg": avg
                    })
                else:
                    st.info(f"No matching data found for **{player_name}**.")

            if summary_stats:
                st.subheader("🏆 Multi-Player Comparison")
                summary_df = pd.DataFrame(summary_stats)

                col1, col2 = st.columns([1, 2])
                with col1:
                    display_df = summary_df.drop(columns=["_raw_ehc", "_raw_avg"]).sort_values("Avg Luck Ratio", ascending=False)
                    st.dataframe(display_df, hide_index=True)
                with col2:
                    chart_data = summary_df.set_index("Player")[["Avg Luck Ratio"]]
                    st.bar_chart(chart_data)

                st.divider()
                st.subheader("🔍 Detailed Breakdowns")

                tabs = st.tabs(list(all_player_tables.keys()))

                for tab, p_name in zip(tabs, all_player_tables.keys()):
                    with tab:
                        p_summary = next(item for item in summary_stats if item["Player"] == p_name)

                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("Account Luck", p_summary["Account Luck"])
                        c2.metric("Avg Luck Ratio", f"{p_summary['_raw_avg']:.2f}")
                        c3.metric("Activities Analyzed", p_summary["Activities Analyzed"])
                        c4.metric("Temple EHC", f"{p_summary['_raw_ehc']:,.1f} hrs")

                        st.table(all_player_tables[p_name])

if __name__ == "__main__":
    main()
