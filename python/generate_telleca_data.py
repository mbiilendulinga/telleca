"""
generate_telleca_data.py
────────────────────────
Generates ~930k rows of interconnected business-logical data for the
telleca database.

Order of generation (respects FK dependencies):
    plans → customers → subscriptions → churn → network_incidents
    → usage_data → payments → service_interactions → customer status update

Every downstream table is shaped by the tables above it:
    - Higher-tier plans → higher usage, stickier customers
    - Prepaid → higher churn, lower overage, mobile-money payments
    - Business plans → international minutes + roaming, bank transfers
    - Home plans → zero voice / zero SMS, always
    - More service interactions + late payments → higher churn probability
"""

import mysql.connector
from mysql.connector import Error
import random
from datetime import date, timedelta
from collections import defaultdict

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
DB_NAME        = "telleca"
MYSQL_HOST     = "localhost"
MYSQL_USER     = "root"
MYSQL_PASSWORD = "password"

random.seed(42)                       # reproducibility

ANALYSIS_START = date(2022, 1, 1)
ANALYSIS_END   = date(2025, 9, 30)

# Hardcoded, deliberately irregular targets — sized to look like a
# real CRM snapshot, not a spec sheet.
TARGET_CUSTOMERS = 20_143
TARGET_INCIDENTS = 6_118

BATCH_SIZE       = 5_000

# ─────────────────────────────────────────────────────────────
# PLANS (13)
# ─────────────────────────────────────────────────────────────
PLANS = [
    # id, name,                    type,      contract,    fee,     data,   voice,    sms, status
    (1,  "Telleca Start",          "Mobile",  "Prepaid",    29.00,   3.00,     60,     60,  "Legacy"),
    (2,  "Telleca Youth",          "Mobile",  "Prepaid",    35.00,   8.00,     50,    300,  "Active"),
    (3,  "Telleca Lite",           "Mobile",  "Prepaid",    49.00,   5.00,    120,    250,  "Active"),
    (4,  "Telleca Smart",          "Mobile",  "Prepaid",    82.00,  12.00,    300,    600,  "Active"),
    (5,  "Telleca Plus",           "Mobile",  "Postpaid",  134.00,  22.00,    550,   1200,  "Active"),
    (6,  "Telleca Max",            "Mobile",  "Postpaid",  197.00,  40.00,   1100,   2500,  "Active"),
    (7,  "Telleca Max Unlimited",  "Mobile",  "12-month",  295.00,  90.00,   3500,   5000,  "Active"),
    (8,  "Telleca Business",       "Business","Postpaid",  355.00,  75.00,   2000,   5000,  "Active"),
    (9,  "Telleca Business Pro",   "Business","12-month",  565.00, 150.00,   4500,  12000,  "Active"),
    (10, "Telleca Enterprise",     "Business","24-month", 1275.00, 400.00,  12000,  25000,  "Active"),
    (11, "Telleca Home Lite",      "Home",    "12-month",  310.00,  60.00,      0,      0,  "Active"),
    (12, "Telleca Home Plus",      "Home",    "12-month",  465.00, 140.00,      0,      0,  "Active"),
    (13, "Telleca Home Max",       "Home",    "24-month",  715.00, 320.00,      0,      0,  "Retired"),
]

PLAN = {p[0]: {"id": p[0], "name": p[1], "type": p[2], "contract": p[3],
               "fee": p[4], "data": p[5], "voice": p[6], "sms": p[7],
               "status": p[8]} for p in PLANS}

# ─────────────────────────────────────────────────────────────
# REFERENCE DATA
# ─────────────────────────────────────────────────────────────
PROVINCES = {
    "Lusaka":        {"w": 0.30, "cities": ["Lusaka", "Kafue", "Chilanga", "Chongwe"]},
    "Copperbelt":    {"w": 0.22, "cities": ["Kitwe", "Ndola", "Chingola", "Mufulira", "Luanshya"]},
    "Southern":      {"w": 0.10, "cities": ["Livingstone", "Choma", "Mazabuka", "Monze"]},
    "Central":       {"w": 0.08, "cities": ["Kabwe", "Kapiri Mposhi", "Mkushi"]},
    "Eastern":       {"w": 0.08, "cities": ["Chipata", "Petauke", "Katete"]},
    "Northern":      {"w": 0.06, "cities": ["Kasama", "Mbala", "Mpika"]},
    "Luapula":       {"w": 0.05, "cities": ["Mansa", "Kawambwa", "Samfya"]},
    "Western":       {"w": 0.04, "cities": ["Mongu", "Kaoma", "Senanga"]},
    "North-Western": {"w": 0.04, "cities": ["Solwezi", "Mwinilunga", "Kasempa"]},
    "Muchinga":      {"w": 0.03, "cities": ["Chinsali", "Mpika", "Isoka"]},
}

INCIDENT_TYPES = [
    "Power Outage", "Fibre Cut", "Tower Down", "Network Congestion",
    "Hardware Failure", "Software Bug", "Weather Damage", "Vandalism"
]

CHURN_REASONS = [
    "Price too high", "Poor coverage", "Better competitor offer",
    "Moved location", "Service quality", "Contract ended",
    "Non-payment", "Other"
]

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def month_iter(start, end):
    """Yield the first of each month from start to end inclusive."""
    cur = date(start.year, start.month, 1)
    while cur <= end:
        yield cur
        cur = date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)

def age_at(dob, ref=ANALYSIS_END):
    return (ref - dob).days // 365

def poisson(lam):
    """Simple Poisson sampler without numpy."""
    L = pow(2.718281828459045, -lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= random.random()
        if p <= L:
            return k - 1

def is_plan_sellable(plan_id, at_date):
    """Legacy plans only before 2023, Retired plans only before 2024."""
    st = PLAN[plan_id]["status"]
    if st == "Active":   return True
    if st == "Legacy":   return at_date < date(2023, 1, 1)
    if st == "Retired":  return at_date < date(2024, 1, 1)
    return False

def log(msg):
    print(f"  → {msg}")

# ─────────────────────────────────────────────────────────────
# CONNECTION
# ─────────────────────────────────────────────────────────────
def connect():
    return mysql.connector.connect(
        host=MYSQL_HOST, user=MYSQL_USER,
        password=MYSQL_PASSWORD, database=DB_NAME
    )

def reset_tables(cursor, conn):
    """Truncate in reverse-FK order so the script is safely re-runnable."""
    print("\n[0/9] Resetting tables...")
    for tbl in ["churn", "service_interactions", "payments",
                "usage_data", "network_incidents", "subscriptions",
                "customers", "plans"]:
        cursor.execute(f"DELETE FROM {tbl}")
        # reset AUTO_INCREMENT if present
        try:
            cursor.execute(f"ALTER TABLE {tbl} AUTO_INCREMENT = 1")
        except Error:
            pass
    conn.commit()
    log("All tables cleared.")

def seed_plans(cursor, conn):
    print("\n[1/9] Seeding plans...")
    cursor.executemany("""
        INSERT INTO plans
            (plan_id, plan_name, plan_type, contract_type,
             monthly_fee, data_allowance_gb, voice_minutes,
             sms_allowance, plan_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, PLANS)
    conn.commit()
    log(f"{len(PLANS)} plans inserted.")

# ─────────────────────────────────────────────────────────────
# 1. CUSTOMERS
# ─────────────────────────────────────────────────────────────
def generate_customers():
    customers = []

    # 88% Individual, 10% Business, 2% Government
    type_pool = ["Individual", "Business", "Government"]
    type_w    = [0.88, 0.10, 0.02]

    prov_keys = list(PROVINCES.keys())
    prov_w    = [PROVINCES[k]["w"] for k in prov_keys]

    for cid in range(1, TARGET_CUSTOMERS + 1):
        gender = random.choices(["Male", "Female"], [0.51, 0.49])[0]

        # DOB: 1960 → 2005
        dob = date(random.randint(1960, 2005),
                   random.randint(1, 12),
                   random.randint(1, 28))

        prov = random.choices(prov_keys, prov_w)[0]
        city = random.choice(PROVINCES[prov]["cities"])

        ctype = random.choices(type_pool, type_w)[0]

        # Acquisition channel depends on customer type
        if ctype == "Business":
            channel = random.choices(
                ["Retail Store", "Online", "Dealer", "Referral", "Corporate"],
                [0.10, 0.15, 0.10, 0.15, 0.50])[0]
        elif ctype == "Government":
            channel = random.choices(
                ["Corporate", "Dealer", "Retail Store"],
                [0.60, 0.25, 0.15])[0]
        else:
            channel = random.choices(
                ["Retail Store", "Online", "Dealer", "Referral", "Corporate"],
                [0.40, 0.25, 0.20, 0.13, 0.02])[0]

        # Registration weighted toward recent years
        total_days = (ANALYSIS_END - ANALYSIS_START).days
        r = random.random() ** 0.65
        reg = ANALYSIS_START + timedelta(days=int(r * total_days))

        # Latent churn-risk per customer (drives churn + interaction volume)
        churn_risk = random.betavariate(2, 8)   # mean ~0.20, mostly low

        customers.append({
            "id": cid, "gender": gender, "dob": dob,
            "province": prov, "city": city,
            "type": ctype, "channel": channel,
            "reg_date": reg,
            "churn_risk": churn_risk,
        })
    return customers

def insert_customers(cursor, conn, customers):
    print("\n[2/9] Inserting customers...")
    rows = [(c["id"], c["gender"], c["dob"], c["province"], c["city"],
             c["type"], c["channel"], c["reg_date"], "Active")
            for c in customers]
    cursor.executemany("""
        INSERT INTO customers
            (customer_id, gender, date_of_birth, province, city,
             customer_type, acquisition_channel, registration_date,
             customer_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, rows)
    conn.commit()
    log(f"{len(rows)} customers inserted.")

# ─────────────────────────────────────────────────────────────
# 2. SUBSCRIPTIONS
# ─────────────────────────────────────────────────────────────
def pick_plan(cust, sub_start, is_secondary):
    age = age_at(cust["dob"], sub_start)
    sellable = [pid for pid in PLAN if is_plan_sellable(pid, sub_start)]

    if cust["type"] == "Business":
        pool   = [p for p in [8, 9, 10] if p in sellable]
        weight = {8: 0.55, 9: 0.33, 10: 0.12}
    elif cust["type"] == "Government":
        pool   = [p for p in [9, 10] if p in sellable]
        weight = {9: 0.40, 10: 0.60}
    else:
        # Individuals: small chance of Home plan if adult
        home_chance = 0.13 if age >= 25 else 0.02
        if random.random() < home_chance:
            pool   = [p for p in [11, 12, 13] if p in sellable]
            weight = {11: 0.55, 12: 0.35, 13: 0.10}
        else:
            if age <= 30:
                pool   = [p for p in [1, 2, 3, 4, 5, 6, 7] if p in sellable]
                weight = {1: 0.03, 2: 0.22, 3: 0.25, 4: 0.20,
                          5: 0.15, 6: 0.10, 7: 0.05}
            else:
                pool   = [p for p in [1, 3, 4, 5, 6, 7] if p in sellable]
                weight = {1: 0.05, 3: 0.22, 4: 0.22,
                          5: 0.20, 6: 0.18, 7: 0.13}

    if not pool:
        pool, weight = [3], {3: 1.0}

    w = [weight[p] for p in pool]
    return random.choices(pool, w)[0]

def generate_subscriptions(customers):
    subs = []
    sub_id = 1

    for cust in customers:
        if cust["type"] == "Individual":
            n = random.choices([1, 2], [0.90, 0.10])[0]
        elif cust["type"] == "Business":
            n = random.choices([1, 2, 3], [0.40, 0.35, 0.25])[0]
        else:
            n = random.choices([1, 2, 3], [0.20, 0.40, 0.40])[0]

        for i in range(n):
            earliest = max(cust["reg_date"], ANALYSIS_START)
            latest   = ANALYSIS_END - timedelta(days=90)
            if i > 0:
                earliest = earliest + timedelta(days=random.randint(180, 720))
            if earliest >= latest:
                continue

            days_range = (latest - earliest).days
            sub_start = earliest + timedelta(days=random.randint(0, days_range))

            plan_id = pick_plan(cust, sub_start, is_secondary=(i > 0))
            plan    = PLAN[plan_id]

            months_active = (ANALYSIS_END - sub_start).days / 30

            if months_active > 24:
                up = random.choices([0, 1, 2, 3], [0.40, 0.35, 0.20, 0.05])[0]
                dn = random.choices([0, 1, 2],      [0.70, 0.25, 0.05])[0]
            elif months_active > 12:
                up = random.choices([0, 1, 2], [0.60, 0.30, 0.10])[0]
                dn = random.choices([0, 1],    [0.80, 0.20])[0]
            else:
                up, dn = 0, 0

            subs.append({
                "id": sub_id, "customer_id": cust["id"],
                "plan_id": plan_id, "start_date": sub_start,
                "end_date": None, "status": "Active",
                "billing_cycle": "Monthly",
                "upgrade_count": up, "downgrade_count": dn,
            })
            sub_id += 1

    return subs

def insert_subscriptions(cursor, conn, subs):
    print("\n[3/9] Inserting subscriptions...")
    rows = [(s["id"], s["customer_id"], s["plan_id"],
             s["start_date"], s["end_date"], s["status"],
             s["billing_cycle"], s["upgrade_count"], s["downgrade_count"])
            for s in subs]
    for i in range(0, len(rows), BATCH_SIZE):
        cursor.executemany("""
            INSERT INTO subscriptions
                (subscription_id, customer_id, plan_id,
                 start_date, end_date, subscription_status,
                 billing_cycle, upgrade_count, downgrade_count)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, rows[i:i+BATCH_SIZE])
    conn.commit()
    log(f"{len(rows)} subscriptions inserted.")

# ─────────────────────────────────────────────────────────────
# 3. CHURN  (decided before usage/payments so they can stop at churn)
# ─────────────────────────────────────────────────────────────
def generate_churn(customers, subs):
    # primary sub per customer (earliest active)
    primary = {}
    for s in subs:
        cid = s["customer_id"]
        if cid not in primary or s["start_date"] < primary[cid]["start_date"]:
            primary[cid] = s

    churn_rows = []
    churn_date_by_customer = {}
    churn_id = 1

    for cust in customers:
        ps = primary.get(cust["id"])
        if ps is None:
            continue
        plan = PLAN[ps["plan_id"]]

        risk = cust["churn_risk"]
        if plan["contract"] == "Prepaid":       risk *= 1.60
        elif plan["contract"] == "Postpaid":    risk *= 1.00
        elif plan["contract"] == "12-month":    risk *= 0.60
        elif plan["contract"] == "24-month":    risk *= 0.40

        if   plan["fee"] < 50:   risk *= 1.40
        elif plan["fee"] < 150:  risk *= 1.00
        elif plan["fee"] < 400:  risk *= 0.80
        else:                    risk *= 0.60

        risk = min(risk, 0.90)
        churned = random.random() < risk

        if churned:
            # churn happens between 3 months after start and ANALYSIS_END
            earliest = ps["start_date"] + timedelta(days=90)
            if earliest >= ANALYSIS_END:
                earliest = ps["start_date"] + timedelta(days=30)
            days = (ANALYSIS_END - earliest).days
            if days <= 0:
                continue
            churn_date = earliest + timedelta(days=random.randint(0, days))
            churn_date_by_customer[cust["id"]] = churn_date

            # reasons skewed by plan type
            if plan["contract"] == "Prepaid":
                reason = random.choices(
                    CHURN_REASONS, [0.30, 0.12, 0.28, 0.05, 0.10, 0.02, 0.08, 0.05])[0]
            elif plan["type"] == "Business":
                reason = random.choices(
                    CHURN_REASONS, [0.20, 0.20, 0.22, 0.05, 0.18, 0.05, 0.05, 0.05])[0]
            else:
                reason = random.choices(
                    CHURN_REASONS, [0.22, 0.15, 0.25, 0.06, 0.15, 0.06, 0.06, 0.05])[0]

            channel = random.choices(
                ["Call Centre", "App", "Retail Store", "WhatsApp", "Email"],
                [0.35, 0.25, 0.20, 0.15, 0.05])[0]

            # retention attempt rate
            attempt_rate = 0.75 if plan["fee"] > 150 else 0.45
            attempted = random.random() < attempt_rate
            if attempted:
                offer = random.choices(
                    ["Discount 20%", "Free data bundle", "Plan downgrade",
                     "Loyalty points", "Device upgrade"],
                    [0.35, 0.25, 0.20, 0.10, 0.10])[0]
                accepted = random.random() < 0.35   # low acceptance
            else:
                offer, accepted = None, None

            churn_rows.append({
                "id": churn_id, "customer_id": cust["id"],
                "status": "Churned", "date": churn_date,
                "reason": reason, "channel": channel,
                "attempted": attempted, "offer": offer, "accepted": accepted,
            })
            churn_id += 1
        else:
            # active customer, no churn event
            churn_rows.append({
                "id": churn_id, "customer_id": cust["id"],
                "status": "Active", "date": None,
                "reason": None, "channel": None,
                "attempted": False, "offer": None, "accepted": None,
            })
            churn_id += 1

    return churn_rows, churn_date_by_customer

def insert_churn(cursor, conn, churn_rows):
    print("\n[4/9] Inserting churn records...")
    rows = [(c["id"], c["customer_id"], c["status"], c["date"],
             c["reason"], c["channel"], c["attempted"],
             c["offer"], c["accepted"]) for c in churn_rows]
    for i in range(0, len(rows), BATCH_SIZE):
        cursor.executemany("""
            INSERT INTO churn
                (churn_id, customer_id, churn_status, churn_date,
                 churn_reason, churn_channel, retention_attempted,
                 retention_offer, retention_accepted)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, rows[i:i+BATCH_SIZE])
    conn.commit()
    churned = sum(1 for c in churn_rows if c["status"] == "Churned")
    log(f"{len(rows)} churn rows inserted ({churned} churned).")

# ─────────────────────────────────────────────────────────────
# 4. NETWORK INCIDENTS
# ─────────────────────────────────────────────────────────────
def generate_incidents():
    incidents = []
    inc_id = 1

    total_days = (ANALYSIS_END - ANALYSIS_START).days
    severity_pool   = ["Low", "Medium", "High", "Critical"]
    severity_w      = [0.42, 0.33, 0.18, 0.07]

    prov_keys = list(PROVINCES.keys())
    prov_w    = [PROVINCES[k]["w"] for k in prov_keys]

    for _ in range(TARGET_INCIDENTS):
        d = ANALYSIS_START + timedelta(days=random.randint(0, total_days))
        prov = random.choices(prov_keys, prov_w)[0]
        city = random.choice(PROVINCES[prov]["cities"])
        itype = random.choice(INCIDENT_TYPES)
        sev = random.choices(severity_pool, severity_w)[0]

        # duration minutes
        if   sev == "Critical": dur = int(random.uniform(180, 900))
        elif sev == "High":     dur = int(random.uniform(60, 360))
        elif sev == "Medium":   dur = int(random.uniform(20, 180))
        else:                   dur = int(random.uniform(5, 60))

        # affected customers scales with province + severity
        base = int(PROVINCES[prov]["w"] * 60000)
        mult = {"Low": 0.005, "Medium": 0.02, "High": 0.06, "Critical": 0.15}[sev]
        affected = max(1, int(base * mult * random.uniform(0.5, 1.5)))

        resolved = random.random() < 0.92
        res_hours = round(dur / 60 * random.uniform(0.9, 1.4), 2) if resolved else None

        incidents.append((inc_id, d, prov, city, itype, sev,
                          dur, affected, resolved, res_hours))
        inc_id += 1
    return incidents

def insert_incidents(cursor, conn, incidents):
    print("\n[5/9] Inserting network incidents...")
    for i in range(0, len(incidents), BATCH_SIZE):
        cursor.executemany("""
            INSERT INTO network_incidents
                (incident_id, incident_date, province, city, incident_type,
                 severity, duration_minutes, affected_customers,
                 resolved, resolution_time_hours)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, incidents[i:i+BATCH_SIZE])
    conn.commit()
    log(f"{len(incidents)} incidents inserted.")

# ─────────────────────────────────────────────────────────────
# 5. USAGE DATA
# ─────────────────────────────────────────────────────────────
def sample_data_usage(plan, tenure_months):
    """Usage relative to plan allowance, by plan type/contract."""
    base = plan["data"]
    if plan["type"] == "Home":
        factor = random.uniform(0.45, 1.05)
    elif plan["type"] == "Business":
        factor = random.uniform(0.65, 1.10)
    elif plan["contract"] == "Prepaid":
        factor = random.uniform(0.45, 1.00)
    else:
        factor = random.uniform(0.70, 1.20)
    # long-tenure customers trend slightly heavier
    factor *= 1 + min(tenure_months, 24) * 0.002
    return round(base * factor, 2)

def sample_voice(plan):
    if plan["voice"] == 0:
        return 0
    factor = random.uniform(0.50, 1.15)
    return int(plan["voice"] * factor)

def sample_sms(plan):
    if plan["sms"] == 0:
        return 0
    factor = random.uniform(0.50, 1.15)
    return int(plan["sms"] * factor)

def sample_intl_roaming(plan):
    if plan["type"] == "Home":
        return 0, 0
    if plan["type"] == "Business":
        return int(random.expovariate(1/80)), int(random.expovariate(1/6))
    if plan["contract"] in ("Postpaid", "12-month", "24-month"):
        return int(random.expovariate(1/20)), int(random.expovariate(1/3))
    return int(random.expovariate(1/8)), int(random.expovariate(1/1.5))

def generate_usage(customers, subs, churn_date_by_customer):
    """One row per customer per active month, based on their primary sub's plan."""
    # primary sub per customer
    primary = {}
    for s in subs:
        cid = s["customer_id"]
        if cid not in primary or s["start_date"] < primary[cid]["start_date"]:
            primary[cid] = s

    usage_id = 1
    batch    = []
    total    = 0

    for cust in customers:
        ps = primary.get(cust["id"])
        if ps is None:
            continue
        plan = PLAN[ps["plan_id"]]

        end = min(ANALYSIS_END,
                  churn_date_by_customer.get(cust["id"], ANALYSIS_END))

        months = list(month_iter(ps["start_date"], end))
        tenure = 0
        for m in months:
            data   = sample_data_usage(plan, tenure)
            voice  = sample_voice(plan)
            sms    = sample_sms(plan)
            intl, roam = sample_intl_roaming(plan)

            batch.append((usage_id, cust["id"], m,
                          data, voice, sms, intl, roam))
            usage_id += 1
            tenure += 1

            if len(batch) >= BATCH_SIZE:
                yield batch
                total += len(batch)
                batch = []

    if batch:
        yield batch

def insert_usage(cursor, conn, generator):
    print("\n[6/9] Inserting usage_data (this is the big one)...")
    total = 0
    for batch in generator:
        cursor.executemany("""
            INSERT INTO usage_data
                (usage_id, customer_id, usage_month,
                 data_used_gb, voice_minutes_used, sms_sent,
                 international_minutes, roaming_days)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, batch)
        total += len(batch)
        if total % 50_000 == 0:
            print(f"     … {total:,} usage rows")
    conn.commit()
    log(f"{total:,} usage rows inserted.")

# ─────────────────────────────────────────────────────────────
# 6. PAYMENTS
# ─────────────────────────────────────────────────────────────
OVERAGE_PER_GB = 4.50

def payment_method(plan):
    if plan["type"] == "Business":
        return random.choices(
            ["Bank Transfer", "Card", "Mobile Money", "Cheque"],
            [0.60, 0.25, 0.10, 0.05])[0]
    if plan["type"] == "Home":
        return random.choices(
            ["Bank Transfer", "Card", "Mobile Money"],
            [0.40, 0.35, 0.25])[0]
    if plan["contract"] == "Prepaid":
        return random.choices(
            ["Mobile Money", "Airtel Money", "Cash", "Card"],
            [0.60, 0.25, 0.10, 0.05])[0]
    return random.choices(
        ["Card", "Mobile Money", "Bank Transfer", "Cash"],
        [0.40, 0.30, 0.20, 0.10])[0]

def sample_late_days(plan):
    """Returns (status, days_late)."""
    if plan["contract"] == "Prepaid":
        r = random.random()
        if r < 0.80: return "Paid", 0
        if r < 0.95: return "Late", random.randint(1, 10)
        return "Late", random.randint(11, 30)
    if plan["type"] == "Business":
        r = random.random()
        if r < 0.65: return "Paid", 0
        if r < 0.85: return "Late", random.randint(1, 30)
        if r < 0.95: return "Late", random.randint(31, 60)
        return "Unpaid", 0
    if plan["type"] == "Home":
        r = random.random()
        if r < 0.75: return "Paid", 0
        if r < 0.90: return "Late", random.randint(1, 20)
        if r < 0.97: return "Late", random.randint(21, 45)
        return "Unpaid", 0
    # postpaid mobile
    r = random.random()
    if r < 0.70: return "Paid", 0
    if r < 0.90: return "Late", random.randint(1, 15)
    if r < 0.98: return "Late", random.randint(16, 45)
    return "Unpaid", 0

def generate_payments(subs, churn_date_by_customer):
    """One payment per subscription per billing month."""
    pay_id = 1
    batch  = []
    total  = 0

    for s in subs:
        plan = PLAN[s["plan_id"]]
        end = min(ANALYSIS_END,
                  churn_date_by_customer.get(s["customer_id"], ANALYSIS_END))

        for m in month_iter(s["start_date"], end):
            # invoice amount = plan fee + potential overage
            invoice = plan["fee"]
            # 25% chance of an overage month for postpaid/contract
            if plan["contract"] != "Prepaid" and random.random() < 0.25:
                over_gb = random.uniform(0.5, 5.0)
                invoice += round(over_gb * OVERAGE_PER_GB, 2)
            invoice = round(invoice, 2)

            status, days_late = sample_late_days(plan)

            if   status == "Paid":  amount = invoice
            elif status == "Late":  amount = invoice
            elif status == "Unpaid":amount = round(invoice * random.uniform(0.0, 0.4), 2)
            else:                   amount = invoice  # fallback

            method = payment_method(plan)

            batch.append((pay_id, s["customer_id"], m,
                          invoice, amount, method, status, days_late))
            pay_id += 1

            if len(batch) >= BATCH_SIZE:
                yield batch
                total += len(batch)
                batch = []

    if batch:
        yield batch

def insert_payments(cursor, conn, generator):
    print("\n[7/9] Inserting payments...")
    total = 0
    for batch in generator:
        cursor.executemany("""
            INSERT INTO payments
                (payment_id, customer_id, payment_date,
                 invoice_amount, amount, payment_method,
                 payment_status, days_late)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, batch)
        total += len(batch)
        if total % 50_000 == 0:
            print(f"     … {total:,} payment rows")
    conn.commit()
    log(f"{total:,} payment rows inserted.")

# ─────────────────────────────────────────────────────────────
# 7. SERVICE INTERACTIONS
# ─────────────────────────────────────────────────────────────
def generate_interactions(customers, subs, churn_date_by_customer):
    # primary sub per customer
    primary = {}
    for s in subs:
        cid = s["customer_id"]
        if cid not in primary or s["start_date"] < primary[cid]["start_date"]:
            primary[cid] = s

    iid = 1
    batch = []
    total = 0

    for cust in customers:
        ps = primary.get(cust["id"])
        if ps is None:
            continue
        plan = PLAN[ps["plan_id"]]
        end = min(ANALYSIS_END,
                  churn_date_by_customer.get(cust["id"], ANALYSIS_END))
        start = ps["start_date"]

        # interaction volume scales with latent churn_risk
        lam = 1.5 + cust["churn_risk"] * 6.0
        if plan["type"] == "Business":
            lam *= 1.30
        n = poisson(lam)

        for _ in range(n):
            days = (end - start).days
            if days <= 0:
                break
            d = start + timedelta(days=random.randint(0, days))

            itype = random.choices(
                ["Complaint", "Enquiry", "Technical", "Billing", "Sales"],
                [0.32, 0.28, 0.18, 0.15, 0.07])[0]

            if itype == "Technical":
                cat = random.choice(["Network", "Data", "Voice", "Device"])
            elif itype == "Billing":
                cat = random.choice(["Billing", "Payment", "Account"])
            elif itype == "Complaint":
                cat = random.choice(["Network", "Billing", "Service", "Data"])
            elif itype == "Enquiry":
                cat = random.choice(["Data", "Account", "Voice"])
            else:
                cat = "Sales"

            channel = random.choices(
                ["Call Centre", "App", "Retail Store", "WhatsApp", "Email"],
                [0.40, 0.22, 0.15, 0.15, 0.08])[0]

            if random.random() < 0.72:
                rstatus = "Resolved"
                res_hours = round(random.expovariate(1/6) + 0.5, 2)
                sat = random.choices([1, 2, 3, 4, 5],
                                     [0.10, 0.12, 0.22, 0.32, 0.24])[0]
            elif random.random() < 0.6:
                rstatus = "Escalated"
                res_hours = round(random.expovariate(1/30) + 8, 2)
                sat = random.choices([1, 2, 3, 4],
                                     [0.35, 0.30, 0.25, 0.10])[0]
            else:
                rstatus = "Unresolved"
                res_hours = round(random.expovariate(1/48) + 12, 2)
                sat = random.choices([1, 2, 3],
                                     [0.55, 0.30, 0.15])[0]

            batch.append((iid, cust["id"], d, itype, cat, channel,
                          rstatus, res_hours, sat))
            iid += 1

            if len(batch) >= BATCH_SIZE:
                yield batch
                total += len(batch)
                batch = []

    if batch:
        yield batch

def insert_interactions(cursor, conn, generator):
    print("\n[8/9] Inserting service interactions...")
    total = 0
    for batch in generator:
        cursor.executemany("""
            INSERT INTO service_interactions
                (interaction_id, customer_id, interaction_date,
                 interaction_type, issue_category, channel,
                 resolution_status, resolution_time_hours,
                 customer_satisfaction)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, batch)
        total += len(batch)
    conn.commit()
    log(f"{total:,} interaction rows inserted.")

# ─────────────────────────────────────────────────────────────
# 8. UPDATE CUSTOMER STATUS from churn
# ─────────────────────────────────────────────────────────────
def update_customer_status(cursor, conn):
    print("\n[9/9] Updating customer status...")
    cursor.execute("""
        UPDATE customers c
        JOIN churn ch ON c.customer_id = ch.customer_id
        SET c.customer_status = 'Churned'
        WHERE ch.churn_status = 'Churned'
    """)
    conn.commit()
    # mark a small slice of late payers as suspended (irregular cap)
    cursor.execute("""
        UPDATE customers c
        SET c.customer_status = 'Suspended'
        WHERE c.customer_status = 'Active'
          AND c.customer_id IN (
              SELECT customer_id FROM (
                  SELECT customer_id
                  FROM payments
                  GROUP BY customer_id
                  HAVING AVG(days_late) > 40 AND COUNT(*) > 6
              ) t
          )
        LIMIT 847
    """)
    conn.commit()
    log("Customer statuses aligned with churn + payment behaviour.")

# ─────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────
def report(cursor):
    print("\n" + "=" * 62)
    print("  TELLECA DATA GENERATION COMPLETE")
    print("=" * 62)

    for tbl in ["plans", "customers", "subscriptions", "network_incidents",
                "usage_data", "payments", "service_interactions", "churn"]:
        cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
        n = cursor.fetchone()[0]
        print(f"  {tbl:<24} {n:>10,}")

    print("\n  Customer status mix:")
    cursor.execute("""
        SELECT customer_status, COUNT(*)
        FROM customers GROUP BY customer_status ORDER BY 2 DESC
    """)
    for status, n in cursor.fetchall():
        print(f"     {status:<12} {n:>8,}")

    print("\n  Subscriptions by plan type:")
    cursor.execute("""
        SELECT p.plan_type, COUNT(*) 
        FROM subscriptions s JOIN plans p ON s.plan_id = p.plan_id
        GROUP BY p.plan_type ORDER BY 2 DESC
    """)
    for t, n in cursor.fetchall():
        print(f"     {t:<12} {n:>8,}")

    print("\n  Churn reasons (top 5):")
    cursor.execute("""
        SELECT churn_reason, COUNT(*) FROM churn
        WHERE churn_status='Churned' AND churn_reason IS NOT NULL
        GROUP BY churn_reason ORDER BY 2 DESC LIMIT 5
    """)
    for r, n in cursor.fetchall():
        print(f"     {r:<24} {n:>8,}")

    print("\n  Data is ready for Power BI / churn modelling.")
    print("=" * 62)

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main():
    conn = connect()
    cursor = conn.cursor()

    try:
        reset_tables(cursor, conn)

        seed_plans(cursor, conn)

        customers = generate_customers()
        insert_customers(cursor, conn, customers)

        subs = generate_subscriptions(customers)
        insert_subscriptions(cursor, conn, subs)

        churn_rows, churn_date_by_customer = generate_churn(customers, subs)
        insert_churn(cursor, conn, churn_rows)

        incidents = generate_incidents()
        insert_incidents(cursor, conn, incidents)

        insert_usage(cursor, conn,
                     generate_usage(customers, subs, churn_date_by_customer))

        insert_payments(cursor, conn,
                        generate_payments(subs, churn_date_by_customer))

        insert_interactions(cursor, conn,
                            generate_interactions(customers, subs,
                                                  churn_date_by_customer))

        update_customer_status(cursor, conn)

        report(cursor)

    except Error as e:
        print(f"\n❌ MySQL error: {e}")
        raise
    finally:
        cursor.close()
        if conn.is_connected():
            conn.close()

if __name__ == "__main__":
    main()