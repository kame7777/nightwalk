import pandas as pd
import osmnx as ox
import glob
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data/"

results = []

csv_files = glob.glob(str(DATA_DIR / "*.csv"))

for csv_path in csv_files:
    print(f"processing: {csv_path}")

    df = None
    for enc in ("utf-8", "shift_jis", "cp932"):
        try:
            df = pd.read_csv(csv_path, encoding=enc)
            break
        except Exception:
            pass

    if df is None:
        print("  -> encoding error, skip")
        continue

    if "市区町村（発生地）" not in df.columns or "町丁目（発生地）" not in df.columns:
        print("  -> invalid columns, skip")
        continue

    df["address"] = (
        df["市区町村（発生地）"].astype(str)
        + df["町丁目（発生地）"].astype(str)
    )

    for address in df["address"].dropna().unique():
        try:
            lat, lon = ox.geocode(address)
            results.append({
                "address": address,
                "lat": lat,
                "lon": lon
            })
        except Exception:
            continue

# 重複除去
out_df = pd.DataFrame(results).drop_duplicates(subset=["address"])

out_path = DATA_DIR / "crime_geocoded.csv"
out_df.to_csv(out_path, index=False)

print(f"saved: {out_path}")
