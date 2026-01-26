import pandas as pd
import json
import os

# --- CONFIG ---
INPUT_CSV = "test.csv"
JSON_DIR = "json_data"
OUTPUT_CSV = "all_with_prices_and_image.csv"

# --- Load CSV ---
df = pd.read_csv(INPUT_CSV, dtype=str)

# Ensure required columns exist
for col in [
    "lowPrice",
    "highPrice",
    "priceCurrency",
    "offerCount",
    "Images",
    "Tags"
]:
    if col not in df.columns:
        df[col] = ""

# Columns to combine into Tags (EXISTING CSV COLUMNS)
TAG_COLUMNS = [
    "Product group",
    "Material",
    "Brand",
    "Type of tablecloth",
    "Shape",
    "Pattern",
    "Theme",
]

# --- Process each row ---
for idx, row in df.iterrows():
    ean = str(row.get("EAN", "")).strip()

    if not ean or ean.lower() == "nan":
        continue

    json_path = os.path.join(JSON_DIR, f"{ean}.json")

    if not os.path.exists(json_path):
        print(f"[MISS] JSON not found for EAN {ean}")
        continue

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # --- subImages (top-level) ---
        sub_images = data.get("subImages", [])

        # --- ld_json ---
        ld_json = data.get("ld_json", [])
        if not isinstance(ld_json, list):
            continue

        for item in ld_json:
            # --- IMAGE ---
            image = item.get("image", {})
            if isinstance(image, dict):
                images = [image.get("url", "")] + sub_images
                images = [i for i in images if i]
                df.at[idx, "Images"] = ",".join(dict.fromkeys(images))

            # --- AGGREGATE OFFER ---
            offers = item.get("offers", {})
            if offers.get("@type") == "AggregateOffer":
                df.at[idx, "lowPrice"] = offers.get("lowPrice", "")
                df.at[idx, "highPrice"] = offers.get("highPrice", "")
                df.at[idx, "priceCurrency"] = offers.get("priceCurrency", "")
                df.at[idx, "offerCount"] = offers.get("offerCount", "")
                break

        # --- TAGS (combine existing CSV columns) ---
        tags = []
        for col in TAG_COLUMNS:
            val = row.get(col)
            if pd.notna(val) and str(val).strip():
                tags.append(str(val).strip())

        df.at[idx, "Tags"] = ",".join(dict.fromkeys(tags))

    except Exception as e:
        print(f"[ERROR] {ean}: {e}")

# --- Save output ---
df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")

print(f"✅ Done. Output saved as {OUTPUT_CSV}")
