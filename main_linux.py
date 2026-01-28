import pandas as pd
import time
import random
import os
import json
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
INPUT_FILE = "all.xlsx"

# Browser path (last one wins)
BRAVE_PATH = "/usr/bin/microsoft-edge"
BRAVE_PATH = "/usr/bin/brave-browser"
BRAVE_PATH = "/snap/bin/chromium"
BRAVE_PATH = "/home/dude/src/out/Default/chrome"

# Profile
USER_DATA_PATH = "/home/dude/.config/google-chrome/"
PROFILE_NAME = "Default"

# Proxy
PROXY_SERVER = "http://127.0.0.1:2080"
PROXY_SERVER = "socks5://127.0.0.1:2002"
LIST_PROXY = [PROXY_SERVER]

JSON_DIR = "json_data"
os.makedirs(JSON_DIR, exist_ok=True)
EAN_INDEX_FILE = "existing_eans.txt"


# ---------------- STATE HELPERS ----------------
def load_existing_eans_from_file(path):
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def save_existing_eans_to_file(eans, path):
    with open(path, "w", encoding="utf-8") as f:
        for ean in sorted(eans):
            f.write(f"{ean}\n")


def load_existing_eans_from_json(json_dir):
    existing_eans = set()

    for fname in os.listdir(json_dir):
        if not fname.endswith(".json"):
            continue

        try:
            with open(os.path.join(json_dir, fname), "r", encoding="utf-8") as f:
                data = json.load(f)

            main_ean = str(data.get("ean", "")).strip()
            if main_ean:
                existing_eans.add(main_ean)

            for block in data.get("ld_json", []):
                variants = block.get("hasVariant", [])
                if isinstance(variants, dict):
                    variants = [variants]

                for v in variants:
                    gtin = str(v.get("gtin13", "")).strip()
                    if gtin:
                        existing_eans.add(gtin)

        except Exception as e:
            print(f"⚠️ Failed reading {fname}: {e}")

    return existing_eans


# ---------------- MAIN SCRAPER ----------------
def scrape_with_custom_chromium():
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Input file not found: {INPUT_FILE}")
        return

    df_input = pd.read_excel(INPUT_FILE)
    df_input["EAN"] = df_input["EAN"].astype(str).str.split(".").str[0]

    # Initial state load (JSON + index file)
    existing_eans = load_existing_eans_from_json(JSON_DIR)
    existing_eans |= load_existing_eans_from_file(EAN_INDEX_FILE)
    save_existing_eans_to_file(existing_eans, EAN_INDEX_FILE)

    print(f"🔁 Loaded {len(existing_eans)} existing EANs")

    remaining_rows = []
    for index, row in df_input.iterrows():
        ean = str(row.get("EAN", "")).strip()
        if not ean or ean in {"nan", "0"}:
            continue
        if ean in existing_eans:
            continue
        remaining_rows.append((index, row))

    random.shuffle(remaining_rows)
    print(f"🔀 {len(remaining_rows)} EANs to scrape")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="",
            executable_path=BRAVE_PATH,
            proxy={"server": PROXY_SERVER} if PROXY_SERVER else {},
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = context.pages[0] if context.pages else context.new_page()
        is_first_time = True

        for index, row in remaining_rows:
            # Reload state before EACH row (crash-safe)
            existing_eans = load_existing_eans_from_file(EAN_INDEX_FILE)

            ean = str(row.get("EAN", "")).strip()
            out_file = os.path.join(JSON_DIR, f"{ean}.json")

            if ean in existing_eans:
                print(f"[{index + 1}] ⏭ Skip existing EAN {ean}")
                continue

            print(f"[{index + 1}] Scraping EAN: {ean}")

            try:
                if not is_first_time:
                    time.sleep(8)
                else:
                    is_first_time = False

                page.goto(
                    f"https://www.bol.com/nl/nl/s/?searchtext={ean}",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                time.sleep(6)

                product_link = page.locator('a[href*="/nl/nl/p/"]').first
                if product_link.count() == 0:
                    print("   ❌ Not found")
                    continue

                href = product_link.get_attribute("href")
                product_url = (
                    f"https://www.bol.com{href}" if href.startswith("/") else href
                )

                page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(2)

                for _ in range(2):
                    page.mouse.wheel(0, random.randint(400, 800))
                    time.sleep(1)

                # -------- JSON-LD --------
                scripts = page.locator(
                    'script[type="application/ld+json"]'
                ).all_inner_texts()

                parsed = []
                new_variant_eans = set()

                for s in scripts:
                    try:
                        obj = json.loads(s)
                        parsed.append(obj)

                        if isinstance(obj, dict) and obj.get("@type") == "ProductGroup":
                            variants = obj.get("hasVariant", [])
                            if isinstance(variants, dict):
                                variants = [variants]

                            for v in variants:
                                gtin = str(v.get("gtin13", "")).strip()
                                if gtin:
                                    new_variant_eans.add(gtin)

                    except Exception:
                        pass

                if not parsed:
                    print("   ❌ No JSON-LD")
                    continue

                # -------- Images --------
                sub_images = []
                try:
                    gallery = page.locator(
                        'div[class*="mb-3"][class*="flex"][class*="overflow-x-auto"]'
                    )
                    if gallery.count() > 0:
                        for img in gallery.locator("img").all():
                            src = img.get_attribute("src")
                            if src and src.startswith("http"):
                                sub_images.append(src)
                except Exception as e:
                    print(f"   ⚠️ Image error: {e}")

                # -------- Save JSON --------
                final_data = {
                    "ean": ean,
                    "ld_json": parsed,
                    "subImages": sub_images,
                }

                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(final_data, f, indent=2, ensure_ascii=False)

                # -------- Update state --------
                existing_eans.add(ean)
                existing_eans.update(new_variant_eans)
                save_existing_eans_to_file(existing_eans, EAN_INDEX_FILE)

                print(f"   ✅ Saved {out_file} (+{len(new_variant_eans)} variants)")

            except Exception as e:
                print(f"   ❌ Error: {e}")

        context.close()

    print("✅ DONE – JSON-LD scraping completed")


if __name__ == "__main__":
    scrape_with_custom_chromium()
