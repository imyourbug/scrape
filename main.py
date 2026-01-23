import pandas as pd
import time
import random
import os
import json
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
INPUT_FILE = "all.xlsx"
CUSTOM_CHROME_PATH = r"D:\chromium\src\out\Default\chrome.exe"
USER_DATA_PATH = os.path.join(
    os.environ["LOCALAPPDATA"], "Google", "Chrome", "User Data"
)

JSON_DIR = "json_data"
os.makedirs(JSON_DIR, exist_ok=True)


def scrape_with_custom_chromium():
    if not os.path.exists(CUSTOM_CHROME_PATH):
        print(f"❌ Chromium not found: {CUSTOM_CHROME_PATH}")
        return

    if not os.path.exists(INPUT_FILE):
        print(f"❌ Input file not found: {INPUT_FILE}")
        return

    # --- Load INPUT ---
    df_input = pd.read_excel(INPUT_FILE)
    df_input["EAN"] = df_input["EAN"].astype(str).str.split(".").str[0]

    # --- Existing JSON files ---
    existing_eans = {
        f.replace(".json", "") for f in os.listdir(JSON_DIR) if f.endswith(".json")
    }

    print(f"🔁 Found {len(existing_eans)} EANs already saved")

    os.system("taskkill /f /im chrome.exe >nul 2>&1")
    time.sleep(2)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_PATH,
            executable_path=CUSTOM_CHROME_PATH,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = context.pages[0] if context.pages else context.new_page()

        for index, row in df_input.iterrows():
            ean = row.get("EAN", "").strip()

            if not ean or ean in {"nan", "0"}:
                continue

            if ean in existing_eans:
                print(f"[SKIP] {ean} already exists")
                continue

            print(f"[{index + 1}] Scraping EAN: {ean}")

            try:
                # --- Search by EAN ---
                search_url = f"https://www.bol.com/nl/nl/s/?searchtext={ean}"
                page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                time.sleep(2)

                product_link = page.locator('a[href*="/nl/nl/p/"]').first

                if product_link.count() == 0:
                    print("   ⚠️ Product not found")
                    continue

                href = product_link.get_attribute("href")
                product_url = (
                    f"https://www.bol.com{href}" if href.startswith("/") else href
                )

                # --- Product page ---
                page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(2)

                # --- Extract ALL JSON-LD ---
                scripts = page.locator(
                    'script[type="application/ld+json"]'
                ).all_inner_texts()

                if not scripts:
                    print("   ❌ No JSON-LD found")
                    continue

                # Save raw JSON-LD content
                output_path = os.path.join(JSON_DIR, f"{ean}.json")

                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(
                        [json.loads(s) for s in scripts],
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )

                print(f"   ✅ JSON-LD saved → {output_path}")
                existing_eans.add(ean)

            except Exception as e:
                print(f"   ❌ Error: {e}")

            time.sleep(random.uniform(1, 2))

        context.close()

    print("✅ DONE – JSON-LD scraping completed")


if __name__ == "__main__":
    scrape_with_custom_chromium()
