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

    # --- Collect remaining rows ---
    remaining_rows = []
    for index, row in df_input.iterrows():
        ean = row.get("EAN", "").strip()
        if not ean or ean in {"nan", "0"}:
            continue
        if ean in existing_eans:
            continue
        remaining_rows.append((index, row))

    # ✅ Shuffle BEFORE scraping
    random.shuffle(remaining_rows)
    print(f"🔀 Shuffled {len(remaining_rows)} EANs")

    # --- Kill existing Chrome ---
    # os.system("taskkill /f /im chrome.exe >nul 2>&1")
    time.sleep(2)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="",
            executable_path=CUSTOM_CHROME_PATH,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = context.pages[0] if context.pages else context.new_page()

        # --- Scrape shuffled EANs ---
        for index, row in remaining_rows:
            ean = row.get("EAN", "").strip()
            if os.path.exists(os.path.join(JSON_DIR, f"{ean}.json")):
                continue
            print(f"[{index + 1}] Scraping EAN: {ean}")

            try:
                time.sleep(12)
                search_url = f"https://www.bol.com/nl/nl/s/?searchtext={ean}"
                page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(9)

                product_link = page.locator('a[href*="/nl/nl/p/"]').first
                if product_link.count() == 0:
                    print("   ❌ Not found")
                    continue

                href = product_link.get_attribute("href")
                product_url = (
                    f"https://www.bol.com{href}" if href.startswith("/") else href
                )

                page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)

                # Scroll to load thumbnails
                for _ in range(2):
                    page.mouse.wheel(0, random.randint(400, 800))
                    time.sleep(1)

                # ---- Extract JSON-LD ----
                scripts = page.locator(
                    'script[type="application/ld+json"]'
                ).all_inner_texts()

                parsed = []
                for s in scripts:
                    try:
                        parsed.append(json.loads(s))
                    except:
                        pass

                if not parsed:
                    print("   ❌ No JSON-LD")

                # ---- Extract sub images ----
                sub_images = []
                try:
                    gallery = page.locator(
                        'div[class*="mb-3"][class*="flex"][class*="overflow-x-auto"]'
                    )

                    if gallery.count() > 0:
                        imgs = gallery.locator("img").all()
                        for img in imgs:
                            src = img.get_attribute("src")
                            if src and src.startswith("http") and src not in sub_images:
                                sub_images.append(src)

                except Exception as e:
                    print(f"   ⚠️ Sub image extract error: {e}")

                # ---- Save combined JSON ----
                final_data = {
                    "ean": ean,
                    "ld_json": parsed,
                    "subImages": sub_images,
                }

                out = os.path.join(JSON_DIR, f"{ean}.json")
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(final_data, f, indent=2, ensure_ascii=False)

                print(f"   ✅ Saved {out}")

            except Exception as e:
                print(f"   ❌ Error: {e}")

        context.close()

    print("✅ DONE – JSON-LD scraping completed")


if __name__ == "__main__":
    scrape_with_custom_chromium()
