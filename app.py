import streamlit as st
import pandas as pd
import requests
import json
import os
import math

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

# --- TEMPLEOSRS API FUNCTIONS ---
@st.cache_data(ttl=3600)
def fetch_player_kc(player_name):
    url = f"https://templeosrs.com/api/player_stats.php?player={player_name}&bosses=1"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.json().get("data", {})
    except: return None

@st.cache_data(ttl=3600)
def fetch_exact_temple_clog(player_name, categories_list):
    """Fetches exactly the categories we need from TempleOSRS."""
    # Join all our JSON keys into a comma-separated string
    categories_str = ",".join(categories_list)

    url = f"https://templeosrs.com/api/collection-log/player_collection_log.php?player={player_name}&categories={categories_str}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # Depending on Temple's exact format, it might be nested under "data"
            return {"success": True, "url": url, "data": data.get("data", data)}
        else:
            return {"success": False, "url": url, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"success": False, "url": url, "error": str(e)}

# --- LUCK LOGIC (LOGARITHMIC) ---
def determine_luck_v2(actual_kc, expected_kc, actual_slots, total_slots, name=""):
    if actual_kc <= 0 or expected_kc <= 0 or total_slots <= 0:
        return "Not Started", 1.0, 0.0

    p = actual_kc / expected_kc
    a = 2 if "barrows" in name.lower() or "clue" in name.lower() else 15
    s_expected_fraction = math.log(1 + a * p) / math.log(1 + a)
    expected_slots = min(total_slots * s_expected_fraction, total_slots)

    safe_actual = max(actual_slots, 0.1)

    if actual_slots >= total_slots:
        ratio = actual_kc / expected_kc
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
    st.markdown("Comparing KC to Expected KC (EKC) weighted by Log Progress via TempleOSRS.")

    clog_data = load_all_clog_data()
    # Extract all the keys (e.g., 'araxxor', 'zulrah') to query the API
    api_keys = list(clog_data.keys())

    with st.sidebar:
        st.header("Player Info")
        player_name = st.text_input("Username", value="Spencejliv")
        filter_type = st.selectbox("Category", ["All", "Boss", "Raid", "Clue"])
        analyze = st.button("Analyze Account", type="primary", use_container_width=True)

    if analyze:
        with st.spinner("Fetching data from TempleOSRS..."):
            kc_api = fetch_player_kc(player_name)
            clog_response = fetch_exact_temple_clog(player_name, api_keys)

        if not kc_api:
            st.error("No hiscore data found. Check the name spelling.")
            return

        clog_api = clog_response.get("data", {}) if clog_response["success"] else {}

        if not clog_response["success"]:
            st.warning(f"⚠️ Failed to pull Collection Log data for '{player_name}'. Error: {clog_response.get('error')}. Defaulting to KC-only math.")

        with st.expander("🔍 Diagnostic: Raw Temple Clog Data"):
            st.write(f"**URL Queried:** {clog_response.get('url')}")
            if clog_api:
                # Show first 3 elements to avoid lag
                st.json({k: clog_api[k] for k in list(clog_api.keys())[:3]})
            else:
                st.write("No valid dictionary returned.")

        # Flatten Temple KC Stats
        flat_kc = {str(k).lower(): v for k, v in kc_api.items()}
        if "bosses" in flat_kc and isinstance(flat_kc["bosses"], dict):
            flat_kc.update({k.lower(): v for k, v in flat_kc["bosses"].items()})

        results = []
        total_r, count = 0, 0

        for key, info in clog_data.items():
            if filter_type != "All" and info["type"] != filter_type:
                continue

            actual_kc = int(flat_kc.get(key.lower(), 0))
            if actual_kc <= 0: continue

            # Direct Dictionary Lookup (So much cleaner!)
            # We look up 'araxxor' directly in the returned Temple data
            boss_clog = clog_api.get(key.lower(), {})

            # Temple might return an array for items, or a dict with "obtained"/"total"
            if isinstance(boss_clog, dict):
                actual_slots = boss_clog.get("obtained", 1)
                total_slots = boss_clog.get("total", 1)
            else:
                actual_slots, total_slots = 1, 1

            status, ratio, exp_slots = determine_luck_v2(
                actual_kc, info["ekc"], actual_slots, total_slots, info["name"]
            )

            display_exp_slots = "N/A" if (total_slots == 1) else round(exp_slots, 1)
            display_kc = f"{actual_kc:,}"

            results.append({
                "Activity": info["name"],
                "Clog Progress": f"{actual_slots}/{total_slots}",
                "Expected Slots": display_exp_slots,
                "Your KC": display_kc,
                "Luck Ratio": round(ratio, 2),
                "Status": status
            })
            total_r += ratio
            count += 1

        if results:
            df = pd.DataFrame(results).sort_values("Luck Ratio", ascending=False)
            st.table(df)

            st.divider()
            avg = total_r / count
            overall = "Overall Spooned 🥄" if avg <= 0.85 else "Overall Dry 🏜️" if avg >= 1.15 else "Overall On-Rate 🎯"

            c1, c2, c3 = st.columns(3)
            c1.metric("Account Luck", overall)
            c2.metric("Avg Luck Ratio", f"{avg:.2f}")
            c3.metric("Activities Analyzed", count)
        else:
            st.info("The player was found, but no KC was found for the selected filters.")

if __name__ == "__main__":
    main()
