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
def fetch_temple_clog_hunter(player_name):
    """Hunts for the correct TempleOSRS Clog endpoint and returns valid JSON."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    # We test all logical TempleOSRS API naming conventions
    endpoints = [
        f"https://templeosrs.com/api/player_collection_log.php?player={player_name}",
        f"https://templeosrs.com/api/player_collectionlog.php?player={player_name}",
        f"https://templeosrs.com/api/collectionlog.php?player={player_name}",
        f"https://templeosrs.com/api/collection_log.php?player={player_name}",
        f"https://templeosrs.com/api/player_clog.php?player={player_name}"
    ]

    debug_logs = {}

    for url in endpoints:
        try:
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                try:
                    data = r.json()
                    if "error" not in data:
                        return {"success": True, "url": url, "data": data, "debug": debug_logs}
                    else:
                        debug_logs[url] = f"API Error: {data['error']}"
                except ValueError:
                    debug_logs[url] = "Status 200, but returned HTML instead of JSON (Wrong URL)"
            else:
                debug_logs[url] = f"Failed with status code: {r.status_code}"
        except Exception as e:
            debug_logs[url] = f"Network Exception: {str(e)}"

    return {"success": False, "data": None, "debug": debug_logs}

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

# --- DYNAMIC TEMPLE PARSER ---
def parse_temple_clog_data(clog_api_data, target_name):
    """Deep searches the Temple JSON payload for the boss name."""
    if not clog_api_data or not isinstance(clog_api_data, dict):
        return {"actual": 1, "total": 1}

    target = target_name.lower()

    def search_dict(d, search_key):
        for k, v in d.items():
            if str(k).lower() == search_key:
                return v
            if isinstance(v, dict):
                res = search_dict(v, search_key)
                if res: return res
        return None

    boss_data = search_dict(clog_api_data, target)

    if isinstance(boss_data, dict):
        # TempleOSRS usually uses 'obtained', 'count', or 'actual'
        actual = boss_data.get("obtained", boss_data.get("count", boss_data.get("actual", 1)))
        total = boss_data.get("total", boss_data.get("max", 1))
        return {"actual": actual, "total": total}

    return {"actual": 1, "total": 1}

# --- MAIN UI ---
def main():
    st.title("OSRS Clog Luck Analyzer")
    st.markdown("Comparing KC to Expected KC (EKC) weighted by Log Progress via TempleOSRS.")

    clog_data = load_all_clog_data()

    with st.sidebar:
        st.header("Player Info")
        player_name = st.text_input("Username", value="B0aty")
        filter_type = st.selectbox("Category", ["All", "Boss", "Raid", "Clue"])
        analyze = st.button("Analyze Account", type="primary", use_container_width=True)

    if analyze:
        with st.spinner("Hunting for TempleOSRS Data..."):
            kc_api = fetch_player_kc(player_name)
            clog_response = fetch_temple_clog_hunter(player_name)

        if not kc_api:
            st.error("No hiscore data found. Check the name spelling.")
            return

        clog_api = clog_response["data"]

        # UI Warnings & Diagnostics
        if not clog_response["success"]:
            st.warning(f"⚠️ We successfully fetched KC, but TempleOSRS returned no Collection Log data for '{player_name}'. Defaulting to 1/1 logic.")

        with st.expander("🔍 Diagnostic: Endpoint Hunter Results"):
            st.write("This shows exactly which URLs were tested and why they failed:")
            st.json(clog_response["debug"])
            if clog_response["success"]:
                st.success(f"Success! Data pulled from: {clog_response['url']}")
                st.write("Raw Payload Format (Snippet):")
                # Only show a small snippet to prevent freezing the UI with massive JSONs
                st.json({k: str(v)[:200] + "..." for k, v in list(clog_api.items())[:3]} if isinstance(clog_api, dict) else "Data is not a dictionary.")

        # Flatten Temple KC Stats
        flat_kc = {str(k).lower(): v for k, v in kc_api.items()}
        if "bosses" in flat_kc and isinstance(flat_kc["bosses"], dict):
            flat_kc.update({k.lower(): v for k, v in flat_kc["bosses"].items()})

        results = []
        total_r, count = 0, 0

        for key, info in clog_data.items():
            if filter_type != "All" and info["type"] != filter_type:
                continue

            # Ensure KC is an integer
            actual_kc = int(flat_kc.get(key.lower(), 0))
            if actual_kc <= 0: continue

            clog_info = parse_temple_clog_data(clog_api, info["name"])

            status, ratio, exp_slots = determine_luck_v2(
                actual_kc, info["ekc"], clog_info["actual"], clog_info["total"], info["name"]
            )

            # Formatting for the table display
            display_exp_slots = "N/A" if (clog_info["total"] == 1) else round(exp_slots, 1)
            display_kc = f"{actual_kc:,}"

            results.append({
                "Activity": info["name"],
                "Clog": f"{clog_info['actual']}/{clog_info['total']}",
                "Expected Slots": display_exp_slots,
                "KC": display_kc,
                "Luck Ratio": round(ratio, 2),
                "Status": status
            })
            total_r += ratio
            count += 1

        if results:
            df = pd.DataFrame(results).sort_values("Luck Ratio", ascending=False)

            # Enforce column types to prevent Pandas from making strings into floats
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
