#!/usr/bin/env python3
"""
LoL Items & Spells Data Updater
Fetches latest League of Legends data from Riot Data Dragon API
and generates txt/json files with EN and RU names.
"""

import json
import os
import re
import ssl
import urllib.request
import urllib.error
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DD_BASE = "https://ddragon.leagueoflegends.com/cdn"
DD_API = "https://ddragon.leagueoflegends.com/api"

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text):
    """Remove HTML tags from a string, replacing <br> with spaces."""
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = _HTML_TAG_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_json(url, timeout=30):
    """Fetch and parse JSON from URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "lol-wiki-bot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        # Retry with unverified SSL on platforms with broken CA stores (some Windows Python builds)
        if "CERTIFICATE_VERIFY_FAILED" in str(e.reason):
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        raise


def get_latest_version():
    """Get latest Data Dragon version."""
    versions = fetch_json(f"{DD_API}/versions.json")
    return versions[0]


def is_arena_id(item_id):
    """Check if item ID belongs to Arena game mode (6+ digit ID)."""
    return len(item_id) >= 6


def unique_by_name(items):
    """Deduplicate items by name, keeping the first occurrence."""
    seen = set()
    result = []
    for item in items:
        key = item["en_name"]
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def fetch_items(version):
    """Fetch items in EN and RU, split by game mode."""
    print("Fetching items (EN + RU)...")
    en = fetch_json(f"{DD_BASE}/{version}/data/en_US/item.json")["data"]
    ru = fetch_json(f"{DD_BASE}/{version}/data/ru_RU/item.json")["data"]

    all_items = []
    for item_id in sorted(en.keys(), key=lambda x: int(x) if x.isdigit() else float("inf")):
        if item_id in ru:
            en_name = strip_html(en[item_id]["name"])
            ru_name = strip_html(ru[item_id]["name"])
            if not en_name or not ru_name:
                continue
            all_items.append({
                "id": item_id,
                "mode": "arena" if is_arena_id(item_id) else "regular",
                "en_name": en_name,
                "ru_name": ru_name,
            })

    # Split by mode, then deduplicate by name
    regular = [i for i in all_items if i["mode"] == "regular"]
    arena = [i for i in all_items if i["mode"] == "arena"]

    regular_unique = unique_by_name(regular)
    arena_unique = unique_by_name(arena)

    print(f"  Regular: {len(regular)} entries -> {len(regular_unique)} unique names")
    print(f"  Arena:   {len(arena)} entries -> {len(arena_unique)} unique names")

    # Remove mode field for output (it was only for splitting)
    for group in (regular_unique, arena_unique):
        for item in group:
            del item["mode"]

    return regular_unique, arena_unique, all_items


def fetch_summoner_spells(version):
    """Fetch summoner spells in EN and RU (deduplicated by name)."""
    print("Fetching summoner spells (EN + RU)...")
    en = fetch_json(f"{DD_BASE}/{version}/data/en_US/summoner.json")["data"]
    ru = fetch_json(f"{DD_BASE}/{version}/data/ru_RU/summoner.json")["data"]

    spells = []
    seen_names = set()
    for spell_id in sorted(en.keys()):
        if spell_id in ru:
            en_name = strip_html(en[spell_id]["name"])
            ru_name = strip_html(ru[spell_id]["name"])
            if not en_name or not ru_name:
                continue
            # Keep only the first occurrence (prefer standard version over Swiftplay/URF variant)
            if en_name in seen_names:
                continue
            seen_names.add(en_name)
            spells.append({
                "id": spell_id,
                "type": "summoner",
                "champion_id": None,
                "en_name": en_name,
                "ru_name": ru_name,
            })
    return spells


def fetch_champion_list(version):
    """Fetch list of all champion IDs."""
    print("Fetching champion list...")
    data = fetch_json(f"{DD_BASE}/{version}/data/en_US/champion.json")["data"]
    return sorted(data.keys())


def fetch_champion_abilities(version, champion_id, locale):
    """Fetch a single champion's abilities."""
    url = f"{DD_BASE}/{version}/data/{locale}/champion/{champion_id}.json"
    data = fetch_json(url)["data"][champion_id]
    return data


def fetch_champion_names(version):
    """Fetch champion names in EN and RU from champion.json."""
    print("Fetching champion names (EN + RU)...")
    en = fetch_json(f"{DD_BASE}/{version}/data/en_US/champion.json")["data"]
    ru = fetch_json(f"{DD_BASE}/{version}/data/ru_RU/champion.json")["data"]

    champions = []
    for cid in sorted(en.keys()):
        if cid in ru:
            champions.append({
                "id": cid,
                "en_name": strip_html(en[cid]["name"]),
                "ru_name": strip_html(ru[cid]["name"]),
            })
    return champions


def fetch_all_abilities(version):
    """Fetch all champion abilities in EN and RU."""
    champions = fetch_champion_list(version)
    print(f"Fetching abilities for {len(champions)} champions...")

    abilities = []

    def process_champion(champ_id):
        try:
            en_data = fetch_champion_abilities(version, champ_id, "en_US")
            ru_data = fetch_champion_abilities(version, champ_id, "ru_RU")

            results = []

            # Passive
            en_passive = en_data.get("passive", {})
            ru_passive = ru_data.get("passive", {})
            if en_passive and ru_passive:
                results.append({
                    "id": f"{champ_id}Passive",
                    "champion_id": champ_id,
                    "type": "passive",
                    "slot": "passive",
                    "en_name": strip_html(en_passive.get("name", "")),
                    "ru_name": strip_html(ru_passive.get("name", "")),
                })

            # Spells (Q/W/E/R)
            en_spells = en_data.get("spells", [])
            ru_spells = ru_data.get("spells", [])
            slots = ["Q", "W", "E", "R"]

            for i, slot in enumerate(slots):
                if i < len(en_spells) and i < len(ru_spells):
                    results.append({
                        "id": en_spells[i].get("id", f"{champ_id}{slot}"),
                        "champion_id": champ_id,
                        "type": "ability",
                        "slot": slot,
                        "en_name": strip_html(en_spells[i].get("name", "")),
                        "ru_name": strip_html(ru_spells[i].get("name", "")),
                    })

            return results
        except Exception as e:
            print(f"  Warning: failed to fetch {champ_id}: {e}")
            return []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_champion, c): c for c in champions}
        for future in as_completed(futures):
            abilities.extend(future.result())

    slot_order = {"passive": 0, "Q": 1, "W": 2, "E": 3, "R": 4}
    abilities.sort(key=lambda a: (a["champion_id"], slot_order.get(a["slot"], 99)))

    return abilities


def write_text_file(filepath, lines):
    """Write lines to a text file with duplicate removal."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    # Remove duplicate lines while keeping blank lines and section headers
    seen = set()
    cleaned = []
    for line in lines:
        key = line.strip()
        # Allow blank lines and section headers to repeat (they separate sections)
        if not key or key.startswith("["):
            if cleaned and line != cleaned[-1]:
                cleaned.append(line)
        elif key not in seen:
            seen.add(key)
            cleaned.append(line)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(cleaned) + "\n" if cleaned else "")
    print(f"  Written: {filepath}")


def write_json_file(filepath, data):
    """Write JSON data to file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Written: {filepath}")


def generate_files(version, items_regular, items_arena, items_all, summoner_spells, abilities, champions):
    """Generate all output files."""
    print("\nGenerating output files...")

    # --- Regular items ---
    write_text_file(
        os.path.join(DATA_DIR, "items_en.txt"),
        [i["en_name"] for i in items_regular],
    )
    write_text_file(
        os.path.join(DATA_DIR, "items_ru.txt"),
        [i["ru_name"] for i in items_regular],
    )
    write_text_file(
        os.path.join(DATA_DIR, "lol_items_en_ru.txt"),
        [f"{i['en_name']} = {i['ru_name']}" for i in items_regular],
    )

    # --- Arena items ---
    write_text_file(
        os.path.join(DATA_DIR, "items_arena_en.txt"),
        [i["en_name"] for i in items_arena],
    )
    write_text_file(
        os.path.join(DATA_DIR, "items_arena_ru.txt"),
        [i["ru_name"] for i in items_arena],
    )
    write_text_file(
        os.path.join(DATA_DIR, "items_arena_en_ru.txt"),
        [f"{i['en_name']} = {i['ru_name']}" for i in items_arena],
    )

    # --- Items JSON (all data, no dedup) ---
    items_json = [{k: v for k, v in i.items() if k != "mode"} for i in items_all]
    write_json_file(os.path.join(DATA_DIR, "items.json"), items_json)

    # --- Spells: en ---
    spell_lines = []
    if summoner_spells:
        spell_lines.append("[Summoner Spells]")
        spell_lines.extend(s["en_name"] for s in summoner_spells)
        spell_lines.append("")
    if abilities:
        spell_lines.append("[Champion Abilities]")
        for a in abilities:
            name = a["en_name"]
            if a["slot"] == "passive":
                spell_lines.append(f"{name} ({a['champion_id']} Passive)")
            else:
                spell_lines.append(f"{name} ({a['champion_id']} {a['slot']})")
    write_text_file(os.path.join(DATA_DIR, "spells_en.txt"), spell_lines)

    # --- Spells: ru ---
    spell_lines_ru = []
    if summoner_spells:
        spell_lines_ru.append("[Summoner Spells]")
        spell_lines_ru.extend(s["ru_name"] for s in summoner_spells)
        spell_lines_ru.append("")
    if abilities:
        spell_lines_ru.append("[Champion Abilities]")
        for a in abilities:
            name = a["ru_name"]
            if a["slot"] == "passive":
                spell_lines_ru.append(f"{name} ({a['champion_id']} Passive)")
            else:
                spell_lines_ru.append(f"{name} ({a['champion_id']} {a['slot']})")
    write_text_file(os.path.join(DATA_DIR, "spells_ru.txt"), spell_lines_ru)

    # --- Spells: JSON ---
    all_spells = summoner_spells + [
        {k: v for k, v in a.items() if k != "slot"} for a in abilities
    ]
    write_json_file(os.path.join(DATA_DIR, "spells.json"), all_spells)

    # --- Combined: all_en.txt ---
    all_en = [i["en_name"] for i in items_regular]
    if summoner_spells:
        all_en.append("")
        all_en.append("[Summoner Spells]")
        all_en.extend(s["en_name"] for s in summoner_spells)
    if abilities:
        all_en.append("")
        all_en.append("[Champion Abilities]")
        for a in abilities:
            name = a["en_name"]
            if a["slot"] == "passive":
                all_en.append(f"{name} ({a['champion_id']} Passive)")
            else:
                all_en.append(f"{name} ({a['champion_id']} {a['slot']})")
    if champions:
        all_en.append("")
        all_en.append("[Champions]")
        all_en.extend(c["en_name"] for c in champions)
    write_text_file(os.path.join(DATA_DIR, "all_en.txt"), all_en)

    # --- Combined: all_ru.txt ---
    all_ru = [i["ru_name"] for i in items_regular]
    if summoner_spells:
        all_ru.append("")
        all_ru.append("[Summoner Spells]")
        all_ru.extend(s["ru_name"] for s in summoner_spells)
    if abilities:
        all_ru.append("")
        all_ru.append("[Champion Abilities]")
        for a in abilities:
            name = a["ru_name"]
            if a["slot"] == "passive":
                all_ru.append(f"{name} ({a['champion_id']} Passive)")
            else:
                all_ru.append(f"{name} ({a['champion_id']} {a['slot']})")
    if champions:
        all_ru.append("")
        all_ru.append("[Champions]")
        all_ru.extend(c["ru_name"] for c in champions)
    write_text_file(os.path.join(DATA_DIR, "all_ru.txt"), all_ru)

    # --- Combined: all_en_ru.txt ---
    all_en_ru = [f"{i['en_name']} = {i['ru_name']}" for i in items_regular]
    if summoner_spells:
        all_en_ru.append("")
        all_en_ru.append("[Summoner Spells]")
        all_en_ru.extend(f"{s['en_name']} = {s['ru_name']}" for s in summoner_spells)
    if abilities:
        all_en_ru.append("")
        all_en_ru.append("[Champion Abilities]")
        for a in abilities:
            name_en = a["en_name"]
            name_ru = a["ru_name"]
            if a["slot"] == "passive":
                all_en_ru.append(f"{name_en} ({a['champion_id']} Passive) = {name_ru} ({a['champion_id']} Passive)")
            else:
                all_en_ru.append(f"{name_en} ({a['champion_id']} {a['slot']}) = {name_ru} ({a['champion_id']} {a['slot']})")
    if champions:
        all_en_ru.append("")
        all_en_ru.append("[Champions]")
        all_en_ru.extend(f"{c['en_name']} = {c['ru_name']}" for c in champions)
    write_text_file(os.path.join(DATA_DIR, "all_en_ru.txt"), all_en_ru)

    # --- Champion names ---
    write_text_file(
        os.path.join(DATA_DIR, "champions_en_ru.txt"),
        [f"{c['en_name']} = {c['ru_name']}" for c in champions],
    )
    write_text_file(
        os.path.join(DATA_DIR, "champions_en.txt"),
        [c["en_name"] for c in champions],
    )
    write_text_file(
        os.path.join(DATA_DIR, "champions_ru.txt"),
        [c["ru_name"] for c in champions],
    )
    write_json_file(os.path.join(DATA_DIR, "champions.json"), champions)

    # --- Version info ---
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    write_text_file(
        os.path.join(DATA_DIR, "version.txt"),
        [f"Patch: {version}", f"Updated: {today}"],
    )

    # Stats
    print(f"\n=== Summary ===")
    print(f"Patch: {version}")
    print(f"Regular items:  {len(items_regular)} (unique names)")
    print(f"Arena items:    {len(items_arena)} (unique names)")
    print(f"Total entries:  {len(items_all)} (with duplicates)")
    print(f"Summoner spells: {len(summoner_spells)}")
    print(f"Champion abilities: {len(abilities)}")
    print(f"Champion names:   {len(champions)}")


def main():
    print("=== LoL Data Updater ===\n")

    try:
        version = get_latest_version()
        print(f"Latest patch: {version}")
    except Exception as e:
        print(f"Error: could not fetch version - {e}")
        return 1

    try:
        items_regular, items_arena, items_all = fetch_items(version)
    except Exception as e:
        print(f"Error: could not fetch items - {e}")
        return 1

    try:
        summoner_spells = fetch_summoner_spells(version)
    except Exception as e:
        print(f"Error: could not fetch summoner spells - {e}")
        return 1

    try:
        abilities = fetch_all_abilities(version)
    except Exception as e:
        print(f"Error: could not fetch abilities - {e}")
        return 1

    try:
        champions = fetch_champion_names(version)
    except Exception as e:
        print(f"Error: could not fetch champion names - {e}")
        return 1

    generate_files(version, items_regular, items_arena, items_all, summoner_spells, abilities, champions)

    return 0


if __name__ == "__main__":
    exit(main())
