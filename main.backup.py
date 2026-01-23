import pandas as pd
import time
import random
import os
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
INPUT_FILE = "all.xlsx"
OUTPUT_CSV = "woocommerce_ready_import.csv"
CUSTOM_CHROME_PATH = r"D:\chromium\src\out\Default\chrome.exe"
USER_DATA_PATH = os.path.join(
    os.environ["LOCALAPPDATA"], "Google", "Chrome", "User Data"
)


def scrape_with_custom_chromium():
    if not os.path.exists(CUSTOM_CHROME_PATH):
        print(f"❌ ERROR: Chromium not found: {CUSTOM_CHROME_PATH}")
        return

    if not os.path.exists(INPUT_FILE):
        print(f"❌ ERROR: Input file not found: {INPUT_FILE}")
        return

    # --- Load INPUT ---
    df_input = pd.read_excel(INPUT_FILE)
    df_input["EAN"] = df_input["EAN"].astype(str).str.split(".").str[0]

    # --- Load OUTPUT (incremental mode) ---
    existing_eans = set()
    if os.path.exists(OUTPUT_CSV):
        df_existing = pd.read_csv(OUTPUT_CSV, dtype=str)
        if "EAN" in df_existing.columns:
            existing_eans = set(df_existing["EAN"].dropna())
        print(f"🔁 Found {len(existing_eans)} already scraped EANs")

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
                print(f"[SKIP] {ean}")
                continue

            print(f"[{index + 1}] Scraping EAN: {ean}")
            images_csv = ""
            is_written = False

            try:
                # --- Search by EAN ---
                search_url = f"https://www.bol.com/nl/nl/s/?searchtext={ean}"
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(2)

                product_link = page.locator('a[href*="/nl/nl/p/"]').first

                if product_link.count() == 0:
                    print("   ⚠️ Product not found")
                else:
                    href = product_link.get_attribute("href")
                    product_url = (
                        f"https://www.bol.com{href}" if href.startswith("/") else href
                    )

                    page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
                    time.sleep(2)

                    # --- Trigger lazy loading ---
                    page.mouse.wheel(0, 1500)
                    time.sleep(1)

                    # 🔥 SUB-IMAGES FROM CLASS-BASED <ul>
                    product_images = []

                    ul = page.locator(
                        "ul.snap-x.snap-mandatory.flex.overflow-hidden.overflow-x-auto"
                    )

                    if ul.count() > 0:
                        imgs = ul.locator("img")

                        for i in range(imgs.count()):
                            img = imgs.nth(i)
                            src = img.get_attribute("src")

                            if not src:
                                continue

                            if "media.s-bol.com" not in src:
                                continue

                            # upscale
                            src = src.replace("/124x124", "/1024x1024")
                            src = src.replace("/124x69", "/1024x1024")
                            src = src.replace("/124x50", "/1024x1024")

                            if src not in product_images:
                                product_images.append(src)

                        print(f"   ✅ {len(product_images)} sub-images found")

                    else:
                        print("   ⚠️ No sub-image <ul> found, fallback to main image")

                        main_img = page.locator('img[src*="media.s-bol.com"]').first
                        src = main_img.get_attribute("src")

                        if src:
                            src = src.replace("/124x124", "/1024x1024")
                            product_images.append(src)
                            print("   ✅ 1 main image captured")

                    if len(product_images) > 0:
                        is_written = True

                    images_csv = ",".join(product_images)

            except Exception as e:
                print(f"   ❌ Error: {e}")

            # --- Write immediately ---
            output_row = row.to_dict()
            output_row["EAN"] = ean
            output_row["Images"] = images_csv

            if is_written:
                pd.DataFrame([output_row]).to_csv(
                    OUTPUT_CSV,
                    mode="a",
                    header=not os.path.exists(OUTPUT_CSV),
                    index=False,
                )

            existing_eans.add(ean)
            time.sleep(random.uniform(1, 2))

        context.close()

    print("✅ DONE – class-based sub-image scraping completed")


if __name__ == "__main__":
    scrape_with_custom_chromium()
