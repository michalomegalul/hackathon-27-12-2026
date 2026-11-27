"""The download ZIP: CSV per table, messy/ CSVs, analyst.duckdb and a Czech data dictionary."""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import duckdb

TABLE_CS = {
    "customers": "zákazníci",
    "stores": "kamenné prodejny",
    "products": "katalog produktů",
    "product_prices": "historie cen produktů (platnost od–do)",
    "orders": "objednávky",
    "order_items": "položky objednávek",
    "payments": "platby (i neúspěšné pokusy)",
    "deliveries": "doručení zásilek",
    "reviews": "recenze produktů",
    "tickets": "tikety zákaznické podpory",
    "suppliers": "dodavatelé",
    "shipments_in": "příjem zboží od dodavatelů (řádky dodávek)",
    "inventory_daily": "denní stav skladu po produktech",
    "subscriptions": "předplatná",
}

# (table, column) first, then the column alone
COLUMN_CS = {
    "customer_id": "identifikátor zákazníka (→ customers)",
    "first_name": "křestní jméno",
    "last_name": "příjmení",
    "gender": "pohlaví",
    "email": "e-mail",
    "phone": "telefon",
    "city": "město",
    "segment": "zákaznický segment",
    "preferred_channel": "kanál, kterým zákazník nakupuje nejčastěji",
    "signup_date": "datum registrace",
    "store_id": "identifikátor prodejny (→ stores); prázdné mimo prodejnu",
    ("stores", "name"): "název prodejny",
    "opened_date": "datum otevření",
    "product_id": "identifikátor produktu (→ products)",
    "sku": "kód produktu (SKU)",
    ("products", "name"): "název produktu",
    "category": "kategorie produktu",
    "supplier_id": "identifikátor dodavatele (→ suppliers)",
    "base_price": "základní cena v Kč",
    "price_id": "identifikátor řádku ceny",
    "price": "cena v Kč v daném období",
    "valid_from": "cena platí od (včetně)",
    "valid_to": "cena platí do (prázdné = dosud)",
    "order_id": "identifikátor objednávky (→ orders)",
    "order_ts": "čas objednávky",
    "order_date": "datum objednávky",
    "channel": "prodejní kanál (eshop, prodejna, …)",
    "subscription_id": "identifikátor předplatného (→ subscriptions); prázdné u běžné objednávky",
    "total_czk": "celková částka objednávky v Kč",
    ("orders", "status"): "stav objednávky",
    "order_item_id": "identifikátor položky",
    "quantity": "počet kusů",
    "unit_price": "cena za kus v Kč",
    "payment_id": "identifikátor platby",
    "attempt": "pořadí pokusu o platbu",
    "paid_ts": "čas platby",
    "method": "způsob platby",
    "amount_czk": "částka v Kč",
    ("payments", "status"): "výsledek platby",
    "delivery_id": "identifikátor doručení",
    "courier": "dopravce",
    "shipped_date": "datum odeslání",
    "promised_date": "slíbené datum doručení",
    "delivered_date": "skutečné datum doručení",
    "delay_days": "zpoždění proti slíbenému datu ve dnech",
    "late": "doručeno pozdě (ano/ne)",
    "review_id": "identifikátor recenze",
    "created_at": "čas vytvoření",
    "review_date": "datum recenze",
    "rating": "hodnocení 1–5 hvězdiček",
    ("reviews", "topic"): "téma recenze",
    ("reviews", "text"): "text recenze (česky)",
    "ticket_id": "identifikátor tiketu",
    ("tickets", "topic"): "téma tiketu",
    "opened_at": "čas otevření tiketu",
    "resolved_at": "čas vyřešení tiketu",
    ("suppliers", "name"): "název dodavatele",
    "lead_time_days": "obvyklá doba dodání ve dnech",
    "reliability": "spolehlivost dodavatele (podíl dodávek včas)",
    "shipment_line_id": "identifikátor řádku dodávky",
    "shipment_id": "identifikátor dodávky",
    "ordered_date": "datum objednání u dodavatele",
    "expected_date": "očekávané datum příjmu",
    "received_date": "skutečné datum příjmu",
    "date": "den",
    "stock_units": "kusů skladem na konci dne",
    "sold_units": "prodaných kusů za den",
    "received_units": "přijatých kusů za den",
    "lost_units": "ztracených/odepsaných kusů za den",
    "plan": "tarif předplatného",
    "started_at": "začátek předplatného",
    "cancelled_at": "zrušení předplatného (prázdné = aktivní)",
    "cancel_reason": "důvod zrušení",
}


def column_cs(table: str, column: str) -> str:
    return COLUMN_CS.get((table, column)) or COLUMN_CS.get(column) or "–"


def _tables(con) -> list[tuple[str, list[tuple[str, str]]]]:
    rows = con.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                       "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position").fetchall()
    out: dict[str, list] = {}
    for t, c, typ in rows:
        out.setdefault(t, []).append((c, typ))
    return list(out.items())


def readme(job_id: str, title: str, tables: list, counts: dict, messy: bool) -> str:
    lines = [f"# Story2Data: {title}", "", f"Úloha `{job_id}`. Data jsou simulovaná, osoby a firmy jsou smyšlené.", "",
             "- `*.csv`: jedna tabulka na soubor (UTF-8, první řádek je hlavička, desetinná tečka)",
             "- `analyst.duckdb`: stejné tabulky v DuckDB (`duckdb analyst.duckdb`)"]
    if messy:
        lines.append("- `messy/*.csv`: „špinavá“ verze téhož exportu (překlepy, chybějící hodnoty, duplicity), "
                     "na čištění dat")
    lines += ["", "## Datový slovník", ""]
    for t, cols in tables:
        lines += [f"### {t}: {TABLE_CS.get(t, '')} ({counts.get(t, 0)} řádků)", "",
                  "| sloupec | typ | popis |", "|---|---|---|"]
        lines += [f"| {c} | {typ} | {column_cs(t, c)} |" for c, typ in cols]
        lines.append("")
    return "\n".join(lines)


def _csvs(db: Path, zf: zipfile.ZipFile, prefix: str, tmp: Path) -> tuple[list, dict]:
    with duckdb.connect(str(db), read_only=True) as con:
        tables = _tables(con)
        counts = {}
        for t, _ in tables:
            path = tmp / f"{prefix.replace('/', '_')}{t}.csv"
            con.execute(f"COPY main.\"{t}\" TO '{path}' (HEADER, DELIMITER ',')")
            counts[t] = con.execute(f'SELECT count(*) FROM main."{t}"').fetchone()[0]
            zf.write(path, f"{prefix}{t}.csv")
            path.unlink()
    return tables, counts


def build_zip(job_dir: Path, job_id: str, title: str) -> Path:
    out = job_dir / "download.zip"
    if out.exists():
        return out
    analyst = job_dir / "analyst.duckdb"
    messy_db = job_dir / "run" / "export.duckdb"
    part = out.with_name("download.zip.tmp")
    with tempfile.TemporaryDirectory(dir=job_dir) as tmpd, \
            zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        tables, counts = _csvs(analyst, zf, "", Path(tmpd))
        messy = messy_db.exists()
        if messy:
            _csvs(messy_db, zf, "messy/", Path(tmpd))
        zf.write(analyst, "analyst.duckdb")
        zf.writestr("README.md", readme(job_id, title, tables, counts, messy))
    part.replace(out)
    return out
