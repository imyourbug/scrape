import json
from pathlib import Path
import shutil

INPUT_DIR = Path("json_data")
OUTPUT_DIR = Path("filtered_json_data")

OUTPUT_DIR.mkdir(exist_ok=True)

seen_product_groups = set()
kept_files = 0

for json_file in INPUT_DIR.glob("*.json"):
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        ld_json = data.get("ld_json", [])
        if not isinstance(ld_json, list) or not ld_json:
            shutil.copy(json_file, OUTPUT_DIR / json_file.name)
            kept_files += 1
            continue

        # Find @id from ProductGroup item
        product_group_id = None
        for item in ld_json:
            if item.get("@type") == "ProductGroup":
                product_group_id = item.get("@id")  # ← use @id instead
                break

        if not product_group_id:
            shutil.copy(json_file, OUTPUT_DIR / json_file.name)
            kept_files += 1
            continue

        # Normalize: strip and lowercase the full @id URL
        normalized_id = product_group_id.strip().lower()

        if normalized_id not in seen_product_groups:
            seen_product_groups.add(normalized_id)
            shutil.copy(json_file, OUTPUT_DIR / json_file.name)
            kept_files += 1

    except Exception as e:
        print(f"Skipping {json_file.name}: {e}")

print(f"Kept {kept_files} files")
print(f"Unique productGroupID kept: {len(seen_product_groups)}")
