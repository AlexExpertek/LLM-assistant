from __future__ import annotations
from pathlib import Path
import json
import yaml
import pandas as pd
from .normalizers import normalize_alloy, normalize_product_type, to_float, clean_text


def load_settings(path: str | Path = "config/settings.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_yaml(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_keywords(path: str | Path) -> tuple[list[str], list[str]]:
    df = pd.read_excel(path)
    include: list[str] = []
    exclude: list[str] = []
    if "keyword" in df.columns:
        include = [str(x).strip().lower() for x in df["keyword"].dropna().tolist() if str(x).strip()]
    if "stop_keyword" in df.columns:
        exclude = [str(x).strip().lower() for x in df["stop_keyword"].dropna().tolist() if str(x).strip()]
    # fallback: collect columns with likely names
    for col in df.columns:
        col_l = str(col).lower()
        if "stop" in col_l and col != "stop_keyword":
            exclude.extend([str(x).strip().lower() for x in df[col].dropna().tolist() if str(x).strip()])
    return sorted(set(include)), sorted(set(exclude))


def load_product_matrix(path: str | Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    # Удаляем пустые служебные колонки
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    rename_map = {
        "thickness_min": "thickness_min_mm",
        "thickness_max": "thickness_max_mm",
        "width_min": "width_min_mm",
        "width_max": "width_max_mm",
    }
    df = df.rename(columns=rename_map)
    if "product_type" in df.columns:
        df["product_type_norm"] = df["product_type"].apply(normalize_product_type)
    else:
        df["product_type_norm"] = None
    if "alloy" in df.columns:
        df["alloy_norm"] = df["alloy"].apply(normalize_alloy)
    else:
        df["alloy_norm"] = None
    for col in ["thickness_min_mm", "thickness_max_mm", "width_min_mm", "width_max_mm", "min_batch", "delivery_time_min", "delivery_time_max"]:
        if col in df.columns:
            df[col] = df[col].apply(to_float)
    return df


def load_rag_documents(rag_dir: str | Path) -> dict[str, str]:
    docs = {}
    for path in Path(rag_dir).glob("*.md"):
        docs[path.name] = path.read_text(encoding="utf-8")
    return docs
