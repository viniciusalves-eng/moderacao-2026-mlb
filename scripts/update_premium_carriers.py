"""
update_premium_carriers.py
Atualiza data_premium_carriers.json com dados reais do BigQuery.
Roda semanalmente via GitHub Actions.
"""

import json
import os
from datetime import datetime, date
from google.cloud import bigquery

PROJECT = "meli-bi-data"
OUTPUT  = os.path.join(os.path.dirname(__file__), "..", "data_premium_carriers.json")

client = bigquery.Client(project=PROJECT)

MONTHS_HIST = ["2026-01","2026-02","2026-03","2026-04","2026-05"]
MONTHS_PROJ = ["2026-06","2026-07","2026-08","2026-09","2026-10","2026-11","2026-12"]

CARRIER_FILTERS = {
    "J3 FLEX":       "('J3 FLEX','J3 FLEX SP','J3 BRASIL EXPRESS LTDA','J3 FLEX MG','J3 MG','J3 FLEX BA')",
    "TM LOGISTICA":  "('TM LOGISTICA','TM Logistica')",
    "FLEX BOYS":     "('FLEX BOYS','FLEX BOYS - SAO PAULO','Flex Boys','FLEXBOYS - BRASILIA','FLEX BOYS - SOROCABA')",
    "VITOM":         "('Vitom SP','VITOM','Vitom Log','VITOM LOG')",
}

FLEX_TOTAL = {
    "2026-01":4290230,"2026-02":4046541,"2026-03":4434329,"2026-04":4482116,"2026-05":4792130,
    "2026-06":5143031,"2026-07":5563094,"2026-08":5867480,"2026-09":5910384,
    "2026-10":6400753,"2026-11":7002869,"2026-12":7996957
}

# ── helpers ──────────────────────────────────────────────────────────────────

def run(sql):
    return list(client.query(sql).result())

def linear_trend(ys, xs=None):
    """Returns (slope, intercept) via least squares over xs=[0,1,...,n-1]."""
    n = len(ys)
    if xs is None:
        xs = list(range(n))
    xm = sum(xs)/n; ym = sum(ys)/n
    num = sum((x-xm)*(y-ym) for x,y in zip(xs,ys))
    den = sum((x-xm)**2 for x in xs)
    slope = num/den if den else 0
    return slope, ym - slope*xm

# ── query: volumes per carrier per month ─────────────────────────────────────

def get_volumes():
    sql = """
    SELECT
      FORMAT_DATE('%Y-%m', DATE(s.SHP_DATETIME_HANDLING_ID)) AS month,
      CASE
        WHEN UPPER(t.CARRIER_NAME) IN ('J3 FLEX','J3 FLEX SP','J3 BRASIL EXPRESS LTDA',
             'J3 FLEX MG','J3 MG','J3 FLEX BA') THEN 'J3 FLEX'
        WHEN UPPER(t.CARRIER_NAME) IN ('TM LOGISTICA','TM LOGÍSTICA') THEN 'TM LOGISTICA'
        WHEN t.CARRIER_NAME IN ('FLEX BOYS','FLEX BOYS - SAO PAULO','Flex Boys',
             'FLEXBOYS - BRASILIA','FLEX BOYS - SOROCABA') THEN 'FLEX BOYS'
        WHEN t.CARRIER_NAME IN ('Vitom SP','VITOM','Vitom Log','VITOM LOG') THEN 'VITOM'
      END AS carrier,
      COUNT(DISTINCT s.SHP_SHIPMENT_ID) AS volume
    FROM `meli-bi-data.WHOWNER.DM_SHP_FLEX_SUMMARY` s
    LEFT JOIN `meli-bi-data.WHOWNER.LK_SHP_FLEX_TRANSPORTATION` t
      ON s.SHP_SHIPMENT_ID = t.SHP_SHIPMENT_ID
    WHERE DATE(s.SHP_DATETIME_HANDLING_ID) BETWEEN '2026-01-01' AND '2026-05-31'
      AND s.SIT_SITE_ID = 'MLB'
      AND s.SHP_PICKING_TYPE_ID = 'self_service'
      AND s.SHP_SHIPPING_MODE_ID = 'me2'
      AND s.SHP_STATUS_ID NOT IN ('cancelled')
      AND t.CARRIER_NAME IN (
        'J3 FLEX','J3 FLEX SP','J3 BRASIL EXPRESS LTDA','J3 FLEX MG','J3 MG','J3 FLEX BA',
        'TM LOGISTICA','TM Logistica','FLEX BOYS','FLEX BOYS - SAO PAULO','Flex Boys',
        'FLEXBOYS - BRASILIA','FLEX BOYS - SOROCABA','Vitom SP','VITOM','Vitom Log','VITOM LOG'
      )
    GROUP BY 1,2
    ORDER BY 1,2
    """
    rows = run(sql)
    result = {c: {} for c in CARRIER_FILTERS}
    for r in rows:
        if r.carrier:
            result[r.carrier][r.month] = r.volume
    return result

# ── query: SLA per carrier per month ─────────────────────────────────────────

def get_sla():
    sql = """
    WITH carr AS (
      SELECT SHP_SHIPMENT_ID,
        CASE
          WHEN UPPER(CARRIER_NAME) IN ('J3 FLEX','J3 FLEX SP','J3 BRASIL EXPRESS LTDA',
               'J3 FLEX MG','J3 MG','J3 FLEX BA') THEN 'J3 FLEX'
          WHEN UPPER(CARRIER_NAME) IN ('TM LOGISTICA','TM LOGÍSTICA') THEN 'TM LOGISTICA'
          WHEN CARRIER_NAME IN ('FLEX BOYS','FLEX BOYS - SAO PAULO','Flex Boys',
               'FLEXBOYS - BRASILIA','FLEX BOYS - SOROCABA') THEN 'FLEX BOYS'
          WHEN CARRIER_NAME IN ('Vitom SP','VITOM','Vitom Log','VITOM LOG') THEN 'VITOM'
        END AS carrier
      FROM `meli-bi-data.WHOWNER.LK_SHP_FLEX_TRANSPORTATION`
    )
    SELECT
      FORMAT_DATE('%Y-%m', DATE(s.PO_UB_DATETIME_TZ)) AS month,
      c.carrier,
      ROUND(COUNTIF(DATE(s.SHP_FIRST_VISIT_DATE_TZ) <= DATE(s.PO_UB_DATETIME_TZ))
        / COUNT(*) * 100, 1) AS sla
    FROM `meli-bi-data.WHOWNER.BT_SHP_SHIPMENTS_SUMMARY` s
    JOIN carr c ON s.SHP_SHIPMENT_ID = c.SHP_SHIPMENT_ID
    WHERE DATE(s.PO_UB_DATETIME_TZ) BETWEEN '2026-01-01' AND '2026-05-31'
      AND s.SIT_SITE_ID = 'MLB'
      AND s.SHP_PICKING_TYPE = 'SELF_SERVICE'
      AND s.SHP_STATUS NOT IN ('CANCELLED')
      AND c.carrier IS NOT NULL
    GROUP BY 1,2
    ORDER BY 1,2
    """
    rows = run(sql)
    result = {c: {} for c in CARRIER_FILTERS}
    for r in rows:
        if r.carrier:
            result[r.carrier][r.month] = float(r.sla)
    return result

# ── query: seller loyalty ─────────────────────────────────────────────────────

def get_seller_loyalty():
    sql = """
    WITH all_sellers AS (
      SELECT
        s.SHP_SENDER_ID AS seller_id,
        CASE
          WHEN UPPER(t.CARRIER_NAME) IN ('J3 FLEX','J3 FLEX SP','J3 BRASIL EXPRESS LTDA',
               'J3 FLEX MG','J3 MG','J3 FLEX BA') THEN 'J3 FLEX'
          WHEN UPPER(t.CARRIER_NAME) IN ('TM LOGISTICA','TM LOGÍSTICA') THEN 'TM LOGISTICA'
          WHEN t.CARRIER_NAME IN ('FLEX BOYS','FLEX BOYS - SAO PAULO','Flex Boys',
               'FLEXBOYS - BRASILIA','FLEX BOYS - SOROCABA') THEN 'FLEX BOYS'
          WHEN t.CARRIER_NAME IN ('Vitom SP','VITOM','Vitom Log','VITOM LOG') THEN 'VITOM'
        END AS primary_carrier,
        t.CARRIER_NAME AS actual_carrier
      FROM `meli-bi-data.WHOWNER.DM_SHP_FLEX_SUMMARY` s
      LEFT JOIN `meli-bi-data.WHOWNER.LK_SHP_FLEX_TRANSPORTATION` t
        ON s.SHP_SHIPMENT_ID = t.SHP_SHIPMENT_ID
      WHERE DATE(s.SHP_DATETIME_HANDLING_ID) BETWEEN '2026-04-01' AND '2026-05-31'
        AND s.SIT_SITE_ID = 'MLB'
        AND s.SHP_PICKING_TYPE_ID = 'self_service'
        AND s.SHP_SHIPPING_MODE_ID = 'me2'
        AND s.SHP_STATUS_ID NOT IN ('cancelled')
    ),
    classified AS (
      SELECT
        seller_id,
        primary_carrier,
        COUNT(*) AS total_shps,
        COUNTIF(
          CASE primary_carrier
            WHEN 'J3 FLEX'      THEN UPPER(actual_carrier) IN ('J3 FLEX','J3 FLEX SP','J3 BRASIL EXPRESS LTDA','J3 FLEX MG','J3 MG','J3 FLEX BA')
            WHEN 'TM LOGISTICA' THEN UPPER(actual_carrier) IN ('TM LOGISTICA','TM LOGÍSTICA')
            WHEN 'FLEX BOYS'    THEN actual_carrier IN ('FLEX BOYS','FLEX BOYS - SAO PAULO','Flex Boys','FLEXBOYS - BRASILIA','FLEX BOYS - SOROCABA')
            WHEN 'VITOM'        THEN actual_carrier IN ('Vitom SP','VITOM','Vitom Log','VITOM LOG')
          END
        ) AS shps_own,
        COUNTIF(actual_carrier IS NULL) AS shps_no_carrier
      FROM all_sellers
      WHERE primary_carrier IS NOT NULL
      GROUP BY 1,2
    )
    SELECT
      primary_carrier AS carrier,
      COUNT(DISTINCT seller_id) AS total_sellers,
      COUNT(DISTINCT IF(total_shps = shps_own AND shps_no_carrier = 0, seller_id, NULL)) AS exclusive,
      COUNT(DISTINCT IF(total_shps > shps_own OR shps_no_carrier > 0, seller_id, NULL)) AS multi_carrier,
      SUM(shps_own) AS shps_own,
      SUM(total_shps - shps_own - shps_no_carrier) AS shps_other,
      SUM(shps_no_carrier) AS shps_no_carrier
    FROM classified
    GROUP BY 1
    """
    rows = run(sql)
    result = {}
    for r in rows:
        total = r.total_sellers or 1
        result[r.carrier] = {
            "total_sellers":       r.total_sellers,
            "exclusive":           r.exclusive,
            "exclusive_pct":       round(r.exclusive / total * 100, 1),
            "multi_carrier":       r.multi_carrier,
            "multi_carrier_pct":   round(r.multi_carrier / total * 100, 1),
            "shps_own":            r.shps_own,
            "shps_other_carrier":  r.shps_other,
            "shps_no_carrier":     r.shps_no_carrier,
        }
    return result

# ── compute trend projections ─────────────────────────────────────────────────

def compute_projections(volumes, flex_total):
    """Returns trend-based projection for Jun-Dec using market share linear trend on M3-M5."""
    ref_months = ["2026-03","2026-04","2026-05"]
    ref_idx    = [0, 1, 2]
    proj = {}
    for carrier, vol in volumes.items():
        shares = [vol.get(m, 0) / flex_total[m] for m in ref_months]
        slope, intercept = linear_trend(shares, ref_idx)
        ms5 = shares[2]
        floor_v   = ms5 * 0.75
        ceiling_v = ms5 * 1.40
        proj[carrier] = {}
        for i, m in enumerate(MONTHS_PROJ):
            raw = intercept + slope * (3 + i)
            clamped = max(floor_v, min(ceiling_v, raw))
            proj[carrier][m] = round(clamped * flex_total[m])
    return proj

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("Fetching volumes...")
    volumes  = get_volumes()
    print("Fetching SLA...")
    sla_data = get_sla()
    print("Fetching seller loyalty...")
    loyalty  = get_seller_loyalty()
    print("Computing projections...")
    projections = compute_projections(volumes, FLEX_TOTAL)

    # Load existing file to preserve static fields (contacts_by_channel, etc.)
    with open(OUTPUT) as f:
        existing = json.load(f)

    existing_map = {c["name"]: c for c in existing["carriers"]}

    # Update each carrier
    for carrier_name in CARRIER_FILTERS:
        c = existing_map.get(carrier_name, {})
        c["name"] = carrier_name

        # Volumes
        c["monthly_volume"] = volumes.get(carrier_name, c.get("monthly_volume", {}))

        # SLA
        c["monthly_sla"] = sla_data.get(carrier_name, c.get("monthly_sla", {}))

        # Projections
        c["projection_trend"] = projections.get(carrier_name, c.get("projection_trend", {}))

        # Loyalty
        if carrier_name in loyalty:
            c["seller_loyalty"] = loyalty[carrier_name]

        # Market share trend (slope)
        ref_months = ["2026-03","2026-04","2026-05"]
        vols = c.get("monthly_volume", {})
        if all(m in vols for m in ref_months):
            shares = [vols[m] / FLEX_TOTAL[m] for m in ref_months]
            slope, _ = linear_trend(shares)
            c["market_share_trend_pp_month"] = round(slope * 100, 3)
            c["market_share_may"] = round(shares[2] * 100, 2)

        existing_map[carrier_name] = c

    existing["carriers"]    = [existing_map[n] for n in CARRIER_FILTERS if n in existing_map]
    existing["updated_at"]  = date.today().isoformat()

    with open(OUTPUT, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"✅ Updated {OUTPUT} at {existing['updated_at']}")

if __name__ == "__main__":
    main()
