import pandas as pd
import re
import requests
from PIL import Image
from io import BytesIO
import imagehash

# ---------------- CONFIG ----------------
INPUT_CSV = "step_2_result.csv"
OUTPUT_CSV = "step_3_result.csv"

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

# ---------------- HELPER FUNCTIONS ----------------


def clean_product_name(name):
    if not isinstance(name, str):
        return name
    name = name.replace("–", "-").replace("—", "-")
    size_pattern = (
        r"(\d+\s*(?:cm|mm|m)?\s*[xX]\s*\d+\s*(?:cm|mm|m)?)|(Ø\s*\d+\s*(?:cm|mm|m)?)"
    )
    name = re.sub(size_pattern, "", name)
    name = name.replace("-", " ")
    return re.sub(r"\s+", " ", name).strip()


def format_number(val):
    if pd.isna(val) or val == "":
        return ""
    return str(val).replace(".", ",")


def get_first_image(image_string):
    if pd.isna(image_string) or str(image_string).strip() == "":
        return ""
    return str(image_string).split(",")[0].strip()


def get_unique_list(series, is_size=False):
    all_values = []
    for val in series.dropna():
        parts = [p.strip() for p in str(val).split(",") if p.strip()]
        all_values.extend(parts)

    unique_values = list(dict.fromkeys(all_values))

    if is_size:

        def extract_sort_value(x):
            # Tìm tất cả số trong chuỗi (ví dụ: "140.0 cm x 180.0 cm" -> [140.0, 180.0])
            nums = re.findall(r"(\d+[.,]?\d*)", str(x))
            if len(nums) >= 2:
                return float(nums[1].replace(",", "."))  # Lấy số thứ 2 (chiều dài)
            if len(nums) == 1:
                return float(nums[0].replace(",", "."))
            return 0.0

        unique_values.sort(key=extract_sort_value)
    else:
        unique_values.sort()

    formatted = []
    for v in unique_values:
        try:
            # Chỉ format nếu nó là số thuần túy, nếu là chuỗi "140 x 180" thì giữ nguyên
            if re.fullmatch(r"(\d+[.,]?\d*)", str(v).strip()):
                num = float(str(v).replace(",", "."))
                formatted.append(str(int(num)) if num.is_integer() else str(v))
            else:
                formatted.append(str(v))
        except:
            formatted.append(str(v))
    return formatted


def get_unique_images(url_list_str, threshold=20):
    if pd.isna(url_list_str) or str(url_list_str).strip() == "":
        return ""
    unique_urls = []
    hashes = []
    urls = [u.strip() for u in str(url_list_str).split(",") if u.strip()]
    for url in urls:
        try:
            response = requests.get(url, timeout=10)
            img = Image.open(BytesIO(response.content))
            current_hash = imagehash.dhash(img)
            is_duplicate = False
            for h in hashes:
                if current_hash - h <= threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                hashes.append(current_hash)
                unique_urls.append(url)
        except Exception as e:
            print(f"Lỗi ảnh {url}: {e}")
    return ",".join(unique_urls)


# ---------------- MAIN TRANSFORM FUNCTION ----------------


def transform_to_wc_format(input_file, output_file, get_all=True):
    df = pd.read_csv(
        input_file, dtype={"Color": str, "Size": str, "EAN": str, "productGroupID": str}
    )

    new_data = []
    grouped = df.groupby("productGroupID")

    for group_id, group in grouped:
        unique_colors = get_unique_list(group["Color"], is_size=False)
        unique_sizes = get_unique_list(group["Size"], is_size=True)

        all_colors_str = ", ".join(unique_colors)
        all_sizes_str = ", ".join(unique_sizes)

        def create_wc_row():
            return {col: "" for col in TARGET_COLUMNS}

        if len(group) == 1:
            orig = group.iloc[0]
            row = create_wc_row()
            row.update(
                {
                    "Type": "simple",
                    "SKU": orig["EAN"] if pd.notna(orig["EAN"]) else f"SKU-{group_id}",
                    "Name": orig["Product name"],
                    "Published": "1",
                    "Visibility in catalog": "visible",
                    "Description": orig.get("Description", ""),
                    "In stock?": "1",
                    "Stock": "999",
                    "Weight (kg)": format_number(orig.get("Product weight", "")),
                    "Length (cm)": format_number(orig.get("Product length", "")),
                    "Width (cm)": format_number(orig.get("Product width", "")),
                    "Height (cm)": format_number(orig.get("Product height", "")),
                    "Sale price": orig.get("Sale price", ""),
                    "Regular price": orig.get("Regular price", ""),
                    "Categories": orig.get("Product group", ""),
                    "Tags": orig.get("Tags", ""),
                    "Brands": orig.get("Brand", ""),
                    "Images": get_unique_images(orig.get("Images", "")),
                    "Attribute 1 name": "Color" if unique_colors else "",
                    "Attribute 1 value(s)": all_colors_str,
                    "Attribute 1 visible": "1",
                    "Attribute 1 global": "0",
                    "Attribute 2 name": "Size" if unique_sizes else "",
                    "Attribute 2 value(s)": all_sizes_str,
                    "Attribute 2 visible": "1",
                    "Attribute 2 global": "0",
                }
            )
            new_data.append(row)

        else:
            orig_first = group.iloc[0]
            parent_sku = f"GRP-{group_id}"
            p_row = create_wc_row()
            p_row.update(
                {
                    "Type": "variable",
                    "SKU": parent_sku,
                    "Name": clean_product_name(orig_first["Product name"]),
                    "Published": "1",
                    "Visibility in catalog": "visible",
                    "Description": orig_first.get("Description", ""),
                    "In stock?": "1",
                    "Stock": "999",
                    "Categories": orig_first.get("Product group", ""),
                    "Tags": orig_first.get("Tags", ""),
                    "Brands": orig_first.get("Brand", ""),
                    "Images": get_unique_images(orig_first.get("Images", "")),
                    "Attribute 1 name": "Color",
                    "Attribute 1 value(s)": all_colors_str,
                    "Attribute 1 visible": "0",
                    "Attribute 1 global": "0",
                    "Attribute 1 default": unique_colors[0] if unique_colors else "",
                    "Attribute 2 name": "Size",
                    "Attribute 2 value(s)": all_sizes_str,
                    "Attribute 2 visible": "0",
                    "Attribute 2 global": "0",
                    "Attribute 2 default": unique_sizes[0] if unique_sizes else "",
                }
            )
            new_data.append(p_row)

            # --- VARIATION (Child) ---
            def sort_key_func(series):
                def extract_last_number(x):
                    if pd.isna(x) or str(x).strip() == "":
                        return 0.0
                    nums = re.findall(r"(\d+[.,]?\d*)", str(x))
                    # Nếu có dạng 140 x 180, lấy 180 (số cuối) để sort
                    if nums:
                        return float(nums[-1].replace(",", "."))
                    return 0.0

                return series.apply(extract_last_number)

            group_sorted = group.sort_values(by="Size", key=sort_key_func)

            count_child = 0
            for idx, v_orig in group_sorted.iterrows():
                v_row = create_wc_row()
                v_row.update(
                    {
                        "Type": "variation",
                        "SKU": (
                            v_orig["EAN"] if pd.notna(v_orig["EAN"]) else f"VAR-{idx}"
                        ),
                        "Name": v_orig["Product name"],
                        "Published": "1",
                        "Visibility in catalog": "visible",
                        "Parent": parent_sku,
                        "Position": count_child,
                        "In stock?": "1",
                        "Stock": "999",
                        "Weight (kg)": format_number(v_orig.get("Product weight", "")),
                        "Length (cm)": format_number(v_orig.get("Product length", "")),
                        "Width (cm)": format_number(v_orig.get("Product width", "")),
                        "Height (cm)": format_number(v_orig.get("Product height", "")),
                        "Sale price": v_orig.get("Sale price", ""),
                        "Regular price": v_orig.get("Regular price", ""),
                        "Images": get_first_image(v_orig.get("Images", "")),
                        "Attribute 1 name": "Color",
                        "Attribute 1 value(s)": v_orig.get("Color", ""),
                        "Attribute 1 global": "0",
                        "Attribute 2 name": "Size",
                        "Attribute 2 value(s)": v_orig.get("Size", ""),
                        "Attribute 2 global": "0",
                    }
                )
                new_data.append(v_row)
                count_child += 1
                # if not get_all and count_child == 3:
                #     break

        if not get_all:
            break

    output_df = pd.DataFrame(new_data, columns=TARGET_COLUMNS)
    output_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"Xong! get_all={get_all}")


if __name__ == "__main__":
    # transform_to_wc_format(INPUT_CSV, OUTPUT_CSV, get_all=False)
    transform_to_wc_format(INPUT_CSV, OUTPUT_CSV, get_all=True)
