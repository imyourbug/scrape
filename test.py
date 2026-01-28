import pandas as pd
import json
import os
import re
import requests
import imagehash
from PIL import Image
from io import BytesIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# ---------------- CONFIG ----------------
INPUT_CSV = "all.csv"
WP_PRODUCTS_CSV = "all_wp_products.csv"  # File chứa sản phẩm đã có trên WP
JSON_DIR = "filtered_json_data"
SIMILARITY_THRESHOLD = 20
MAX_WORKERS = 10
CHUNK_SIZE = 15

TAG_COLUMNS = [
    "Product group",
    "Material",
    "Type of tablecloth",
    "Shape",
    "Pattern",
    "Theme",
]
TARGET_COLUMNS = [
    "Type",
    "SKU",
    "Name",
    "Published",
    "Is featured?",
    "Visibility in catalog",
    "Short description",
    "Description",
    "In stock?",
    "Stock",
    "Weight (kg)",
    "Length (cm)",
    "Width (cm)",
    "Height (cm)",
    "Sale price",
    "Regular price",
    "Categories",
    "Tags",
    "Images",
    "Parent",
    "Brands",
    "Position",
    "Attribute 1 name",
    "Attribute 1 value(s)",
    "Attribute 1 visible",
    "Attribute 1 global",
    "Attribute 1 default",
    "Attribute 2 name",
    "Attribute 2 value(s)",
    "Attribute 2 visible",
    "Attribute 2 global",
    "Attribute 2 default",
]

CSV_DATA_LOOKUP = {}
EXISTING_SKUS = set()

# ---------------- UTILS ----------------


def load_existing_skus(file_path):
    """Đọc file all_wp_products.csv và lấy tất cả SKU hiện có."""
    global EXISTING_SKUS
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path, dtype=str)
            if "SKU" in df.columns:
                EXISTING_SKUS = set(df["SKU"].str.strip().tolist())
                print(f"Loaded {len(EXISTING_SKUS)} existing SKUs from {file_path}")
        except Exception as e:
            print(f"Error loading {file_path}: {e}")


def load_csv_lookup(file_path):
    global CSV_DATA_LOOKUP
    df = pd.read_csv(file_path, dtype=str)
    if df["EAN"].duplicated().any():
        df = df.drop_duplicates(subset="EAN", keep="first")
    CSV_DATA_LOOKUP = df.set_index("EAN").to_dict(orient="index")


def get_csv_value(ean, column_name):
    ean_str = str(ean).strip()
    row = CSV_DATA_LOOKUP.get(ean_str)
    if row:
        val = row.get(column_name, "")
        return str(val).strip() if pd.notna(val) else ""
    return ""


def clean_dim(val):
    if not val or str(val).lower() == "nan":
        return ""
    s = str(val).strip()
    return s[:-2] if s.endswith(".0") else s


def size_sort_key(size_str):
    nums = re.findall(r"(\d+[.,]?\d*)", str(size_str))
    return [float(n.replace(",", ".")) for n in nums] if nums else [0.0]


def fetch_and_hash(url):
    try:
        response = requests.get(url, timeout=10, stream=True)
        img = Image.open(BytesIO(response.content))
        return imagehash.phash(img)
    except:
        return None


def filter_unique_images(urls_list):
    urls = [u.strip() for u in urls_list if u.strip()]
    if not urls:
        return ""
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        hash_results = list(executor.map(fetch_and_hash, urls))
    unique_urls, accepted_hashes = [], []
    for url, current_hash in zip(urls, hash_results):
        if current_hash is None:
            unique_urls.append(url)
            continue
        if not any(current_hash - h <= SIMILARITY_THRESHOLD for h in accepted_hashes):
            accepted_hashes.append(current_hash)
            unique_urls.append(url)
    return ", ".join(unique_urls)


# ---------------- CORE PROCESSING ----------------


def run_conversion():
    load_csv_lookup(INPUT_CSV)
    load_existing_skus(WP_PRODUCTS_CSV)
    all_final_rows = []

    for fname in os.listdir(JSON_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(JSON_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ld_json = data.get("ld_json", [])
            sub_images = data.get("subImages", [])
            if not isinstance(ld_json, list):
                continue

            for group_item in ld_json:
                # --- CASE 1: PRODUCT GROUP ---
                if group_item.get("@type") == "ProductGroup":
                    # group_id = group_item.get("productGroupID", "GRP-" + fname)
                    group_id = "RAV-RAVEDTAFEL-" + group_item.get(
                        "productGroupID", fname
                    )
                    variants_data = group_item.get("hasVariant", [])
                    if not isinstance(variants_data, list):
                        variants_data = [group_item]

                    processed_variants = {}  # Dùng để lọc trùng Size

                    for v in variants_data:
                        gtin = str(v.get("gtin13", "")).strip()

                        # 1. Check SKU tồn tại
                        if gtin in EXISTING_SKUS:
                            print(f"GTIN {gtin} existing")
                            continue

                        if gtin in CSV_DATA_LOOKUP:
                            match_info = CSV_DATA_LOOKUP[gtin].copy()
                            w, l = (
                                clean_dim(match_info.get("Product width")),
                                clean_dim(match_info.get("Product length")),
                            )
                            unit = str(match_info.get("Product width Unit", "")).strip()
                            size_str = f"{w} x {l} {unit}".strip() if w and l else ""

                            # 2. Nếu đã có size này rồi thì skip (Bỏ qua các color khác)
                            if size_str in processed_variants:
                                continue

                            match_info["EAN"] = gtin
                            match_info["Size"] = size_str
                            match_info["Sale price"] = group_item.get("offers", {}).get(
                                "lowPrice", ""
                            )
                            match_info["Regular price"] = group_item.get(
                                "offers", {}
                            ).get("highPrice", "")
                            match_info["Image"] = v.get("image", {}).get("url", "")
                            processed_variants[size_str] = match_info

                    variant_list = list(processed_variants.values())
                    if not variant_list:
                        continue

                    variant_list.sort(key=lambda x: size_sort_key(x["Size"]))

                    # Xử lý ảnh chung cho Group
                    all_raw_imgs = [
                        group_item.get("image", {}).get("url", "")
                    ] + sub_images
                    parent_images = filter_unique_images(
                        list(dict.fromkeys(all_raw_imgs))
                    )
                    first_img = parent_images.split(",")[0] if parent_images else ""

                    # 3. Logic: Nếu chỉ có 1 variant -> Chuyển thành Simple
                    if len(variant_list) == 1:
                        vr = variant_list[0]
                        gtin = vr["EAN"]
                        item_tags = [
                            get_csv_value(gtin, col)
                            for col in TAG_COLUMNS
                            if get_csv_value(gtin, col)
                        ]
                        brand = get_csv_value(gtin, "Brand")
                        if brand:
                            item_tags.append(brand)

                        s_row = {col: "" for col in TARGET_COLUMNS}
                        s_row.update(
                            {
                                "Type": "simple",
                                "SKU": gtin,
                                "Name": group_item.get("name", ""),
                                "Description": group_item.get("description", ""),
                                "Published": "1",
                                "Visibility in catalog": "visible",
                                "In stock?": "1",
                                "Stock": "999",
                                "Regular price": vr["Regular price"],
                                "Sale price": vr["Sale price"],
                                "Categories": get_csv_value(gtin, "Product group"),
                                "Brands": brand,
                                "Tags": ",".join(dict.fromkeys(item_tags)),
                                "Images": parent_images,
                            }
                        )
                        all_final_rows.append(s_row)

                    else:
                        # Tạo row VARIABLE và VARIATION như cũ
                        first_ean = variant_list[0]["EAN"]
                        parent_category = get_csv_value(first_ean, "Product group")
                        parent_brand = get_csv_value(first_ean, "Brand")
                        group_tags = []
                        for vr in variant_list:
                            for col in TAG_COLUMNS:
                                val = get_csv_value(vr["EAN"], col)
                                if val:
                                    group_tags.append(val)
                            if parent_brand:
                                group_tags.append(parent_brand)

                        p_row = {col: "" for col in TARGET_COLUMNS}
                        unique_sizes = [v["Size"] for v in variant_list if v["Size"]]
                        p_row.update(
                            {
                                "Type": "variable",
                                "SKU": group_id,
                                "Name": group_item.get("name", ""),
                                "Description": group_item.get("description", ""),
                                "Published": "1",
                                "Visibility in catalog": "visible",
                                "In stock?": "1",
                                "Stock": "999",
                                "Images": parent_images,
                                "Tags": ",".join(dict.fromkeys(group_tags)),
                                "Brands": parent_brand,
                                "Categories": parent_category,
                                "Attribute 1 name": "Size",
                                "Attribute 1 value(s)": ", ".join(unique_sizes),
                                "Attribute 1 visible": "0",
                                "Attribute 1 global": "0",
                                "Attribute 1 default": unique_sizes[0]
                                if unique_sizes
                                else "",
                            }
                        )
                        all_final_rows.append(p_row)

                        for idx, vr in enumerate(variant_list):
                            v_row = {col: "" for col in TARGET_COLUMNS}
                            v_row.update(
                                {
                                    "Type": "variation",
                                    "Parent": group_id,
                                    "Published": "1",
                                    "SKU": vr["EAN"],
                                    "Name": vr.get("Product name", ""),
                                    "Position": idx,
                                    "Regular price": vr["Regular price"],
                                    "Sale price": vr["Sale price"],
                                    "Images": vr["Image"] or first_img,
                                    "In stock?": "1",
                                    "Stock": "999",
                                    "Visibility in catalog": "visible",
                                    "Categories": get_csv_value(
                                        vr["EAN"], "Product group"
                                    ),
                                    "Brands": get_csv_value(vr["EAN"], "Brand"),
                                    "Attribute 1 name": "Size",
                                    "Attribute 1 global": "0",
                                    "Attribute 1 value(s)": vr["Size"],
                                }
                            )
                            all_final_rows.append(v_row)

                # --- CASE 2: SINGLE PRODUCT ---
                elif group_item.get("@type") == "Product":
                    gtin = str(group_item.get("gtin13", "")).strip()
                    if gtin in EXISTING_SKUS:
                        continue

                    if gtin in CSV_DATA_LOOKUP:
                        item_tags = [
                            get_csv_value(gtin, col)
                            for col in TAG_COLUMNS
                            if get_csv_value(gtin, col)
                        ]
                        brand = get_csv_value(gtin, "Brand")
                        if brand:
                            item_tags.append(brand)
                        raw_imgs = [
                            group_item.get("image", {}).get("url", "")
                        ] + sub_images
                        filtered_imgs = filter_unique_images(
                            list(dict.fromkeys(raw_imgs))
                        )

                        s_row = {col: "" for col in TARGET_COLUMNS}
                        s_row.update(
                            {
                                "Type": "simple",
                                "SKU": gtin,
                                "Name": group_item.get("name", ""),
                                "Description": group_item.get("description", ""),
                                "Published": "1",
                                "Visibility in catalog": "visible",
                                "In stock?": "1",
                                "Stock": "999",
                                "Regular price": group_item.get("offers", {}).get(
                                    "price", ""
                                ),
                                "Sale price": group_item.get("offers", {}).get(
                                    "lowPrice", ""
                                ),
                                "Categories": get_csv_value(gtin, "Product group"),
                                "Brands": brand,
                                "Tags": ",".join(dict.fromkeys(item_tags)),
                                "Images": filtered_imgs,
                            }
                        )
                        all_final_rows.append(s_row)

        except Exception as e:
            print(f"Error processing {fname}: {e}")

    save_chunks(all_final_rows, "wc_output.csv")


def save_chunks(data_list, base_filename):
    Path("result").mkdir(exist_ok=True)
    product_starts = [
        i for i, row in enumerate(data_list) if row["Type"] in ["variable", "simple"]
    ]
    for i in range(0, len(product_starts), CHUNK_SIZE):
        start_idx = product_starts[i]
        end_idx = (
            product_starts[i + CHUNK_SIZE]
            if i + CHUNK_SIZE < len(product_starts)
            else len(data_list)
        )
        chunk = data_list[start_idx:end_idx]
        idx = (i // CHUNK_SIZE) + 1
        pd.DataFrame(chunk).to_csv(
            f"result/{base_filename.replace('.csv', '')}_{idx}.csv",
            index=False,
            encoding="utf-8-sig",
        )


if __name__ == "__main__":
    run_conversion()
