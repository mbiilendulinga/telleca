# report.py
import mysql.connector
from mysql.connector import Error
from decimal import Decimal
import datetime

DB_NAME = "telleca"
MYSQL_HOST = "localhost"
MYSQL_USER = "root"
MYSQL_PASSWORD = "password"


def fmt(v):
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    if isinstance(v, (datetime.date, datetime.datetime)):
        return str(v)
    return str(v)


def section(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def run(cursor, title, query):
    section(title)
    try:
        cursor.execute(query)
        cols = [d[0] for d in cursor.description]
        print(" | ".join(cols))
        print("-" * 70)
        rows = cursor.fetchall()
        if not rows:
            print("(no data)")
        for r in rows:
            print(" | ".join(fmt(x) for x in r))
    except Error as e:
        print(f"ERROR: {e}")


def main():
    connection = None
    cursor = None
    try:
        connection = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=DB_NAME
        )
        cursor = connection.cursor()

        # =========================================================
        # EXECUTIVE OVERVIEW
        # =========================================================

        run(cursor, "1. TOTAL CUSTOMERS VS RETAINED OVER TIME (monthly)",
            """
            SELECT DATE_FORMAT(c.registration_date, '%Y-%m') AS month,
                   COUNT(DISTINCT c.customer_id) AS total_customers,
                   COUNT(DISTINCT CASE WHEN ch.churn_status = 'Retained'
                                        OR ch.churn_status IS NULL
                                        THEN c.customer_id END) AS retained_customers,
                   COUNT(DISTINCT CASE WHEN ch.churn_status = 'Churned'
                                        THEN c.customer_id END) AS churned_customers
            FROM customers c
            LEFT JOIN churn ch ON ch.customer_id = c.customer_id
            GROUP BY month
            ORDER BY month
            """)

        run(cursor, "2. SUBSCRIBERS BY PLAN",
            """
            SELECT p.plan_id, p.plan_name, p.plan_type,
                   COUNT(s.subscription_id) AS subscribers
            FROM plans p
            LEFT JOIN subscriptions s ON s.plan_id = p.plan_id
            GROUP BY p.plan_id, p.plan_name, p.plan_type
            ORDER BY subscribers DESC
            """)

        run(cursor, "3. CHURN RATE BY CONTRACT TYPE",
            """
            SELECT p.contract_type,
                   COUNT(DISTINCT s.customer_id) AS total_customers,
                   COUNT(DISTINCT CASE WHEN ch.churn_status = 'Churned'
                                       THEN s.customer_id END) AS churned,
                   ROUND(100.0 * COUNT(DISTINCT CASE WHEN ch.churn_status = 'Churned'
                                                     THEN s.customer_id END)
                         / NULLIF(COUNT(DISTINCT s.customer_id),0), 2) AS churn_rate_pct
            FROM subscriptions s
            JOIN plans p ON p.plan_id = s.plan_id
            LEFT JOIN churn ch ON ch.customer_id = s.customer_id
            GROUP BY p.contract_type
            ORDER BY churn_rate_pct DESC
            """)

        run(cursor, "3b. RETENTION / RETAINED CUSTOMERS BY CONTRACT TYPE",
            """
            SELECT p.contract_type,
                   COUNT(DISTINCT s.customer_id) AS total_customers,
                   COUNT(DISTINCT CASE WHEN ch.churn_status = 'Retained'
                                       THEN s.customer_id END) AS retained,
                   ROUND(100.0 * COUNT(DISTINCT CASE WHEN ch.churn_status = 'Retained'
                                                     THEN s.customer_id END)
                         / NULLIF(COUNT(DISTINCT s.customer_id),0), 2) AS retention_rate_pct
            FROM subscriptions s
            JOIN plans p ON p.plan_id = s.plan_id
            LEFT JOIN churn ch ON ch.customer_id = s.customer_id
            GROUP BY p.contract_type
            ORDER BY retention_rate_pct DESC
            """)

        run(cursor, "3c. CHURN RATE BY PLAN",
            """
            SELECT p.plan_id, p.plan_name,
                   COUNT(DISTINCT s.customer_id) AS total_customers,
                   COUNT(DISTINCT CASE WHEN ch.churn_status = 'Churned'
                                       THEN s.customer_id END) AS churned,
                   ROUND(100.0 * COUNT(DISTINCT CASE WHEN ch.churn_status = 'Churned'
                                                     THEN s.customer_id END)
                         / NULLIF(COUNT(DISTINCT s.customer_id),0), 2) AS churn_rate_pct
            FROM subscriptions s
            JOIN plans p ON p.plan_id = s.plan_id
            LEFT JOIN churn ch ON ch.customer_id = s.customer_id
            GROUP BY p.plan_id, p.plan_name
            ORDER BY churn_rate_pct DESC
            """)

        run(cursor, "3d. CHURN RATE BY GENDER",
            """
            SELECT c.gender,
                   COUNT(DISTINCT c.customer_id) AS total_customers,
                   COUNT(DISTINCT CASE WHEN ch.churn_status = 'Churned'
                                       THEN c.customer_id END) AS churned,
                   ROUND(100.0 * COUNT(DISTINCT CASE WHEN ch.churn_status = 'Churned'
                                                     THEN c.customer_id END)
                         / NULLIF(COUNT(DISTINCT c.customer_id),0), 2) AS churn_rate_pct
            FROM customers c
            LEFT JOIN churn ch ON ch.customer_id = c.customer_id
            GROUP BY c.gender
            ORDER BY churn_rate_pct DESC
            """)

        run(cursor, "4. CUSTOMER MIX (customer_type)",
            """
            SELECT customer_type, COUNT(*) AS customers,
                   ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM customers), 2) AS pct
            FROM customers
            GROUP BY customer_type
            ORDER BY customers DESC
            """)

        run(cursor, "5. CUSTOMER STATUS MIX",
            """
            SELECT customer_status, COUNT(*) AS customers,
                   ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM customers), 2) AS pct
            FROM customers
            GROUP BY customer_status
            ORDER BY customers DESC
            """)

        run(cursor, "6. TOTAL REVENUE BY PROVINCE",
            """
            SELECT c.province,
                   ROUND(SUM(p.amount), 2) AS total_revenue,
                   COUNT(p.payment_id) AS payments
            FROM payments p
            JOIN customers c ON c.customer_id = p.customer_id
            WHERE p.payment_status IN ('Paid','Completed','Success')
            GROUP BY c.province
            ORDER BY total_revenue DESC
            """)

        run(cursor, "7. TOTAL REVENUE BY YEAR",
            """
            SELECT YEAR(payment_date) AS year,
                   ROUND(SUM(amount), 2) AS total_revenue
            FROM payments
            WHERE payment_status IN ('Paid','Completed','Success')
            GROUP BY year
            ORDER BY year
            """)

        run(cursor, "8. TOTAL REVENUE BY MONTH",
            """
            SELECT DATE_FORMAT(payment_date, '%Y-%m') AS month,
                   ROUND(SUM(amount), 2) AS total_revenue
            FROM payments
            WHERE payment_status IN ('Paid','Completed','Success')
            GROUP BY month
            ORDER BY month
            """)

        # =========================================================
        # CUSTOMER BEHAVIOR
        # =========================================================

        run(cursor, "9. TOTAL CUSTOMERS BY ACQUISITION CHANNEL",
            """
            SELECT acquisition_channel, COUNT(*) AS customers,
                   ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM customers), 2) AS pct
            FROM customers
            GROUP BY acquisition_channel
            ORDER BY customers DESC
            """)

        run(cursor, "10. AVERAGE DATA USAGE BY PLAN",
            """
            SELECT p.plan_name,
                   ROUND(AVG(u.data_used_gb), 2) AS avg_data_gb
            FROM usage_data u
            JOIN subscriptions s ON s.customer_id = u.customer_id
            JOIN plans p ON p.plan_id = s.plan_id
            GROUP BY p.plan_name
            ORDER BY avg_data_gb DESC
            """)

        run(cursor, "11. AVERAGE VOICE USAGE BY PLAN",
            """
            SELECT p.plan_name,
                   ROUND(AVG(u.voice_minutes_used), 2) AS avg_voice_minutes
            FROM usage_data u
            JOIN subscriptions s ON s.customer_id = u.customer_id
            JOIN plans p ON p.plan_id = s.plan_id
            GROUP BY p.plan_name
            ORDER BY avg_voice_minutes DESC
            """)

        run(cursor, "12. SUBSCRIBER DISTRIBUTION BY PLAN",
            """
            SELECT p.plan_name, COUNT(s.subscription_id) AS subscribers,
                   ROUND(100.0 * COUNT(s.subscription_id)
                         / (SELECT COUNT(*) FROM subscriptions), 2) AS pct
            FROM plans p
            LEFT JOIN subscriptions s ON s.plan_id = p.plan_id
            GROUP BY p.plan_name
            ORDER BY subscribers DESC
            """)

        run(cursor, "13. AVERAGE SMS USAGE BY PLAN",
            """
            SELECT p.plan_name,
                   ROUND(AVG(u.sms_sent), 2) AS avg_sms
            FROM usage_data u
            JOIN subscriptions s ON s.customer_id = u.customer_id
            JOIN plans p ON p.plan_id = s.plan_id
            GROUP BY p.plan_name
            ORDER BY avg_sms DESC
            """)

        run(cursor, "14. SERVICE INTERACTION RESOLUTION STATUS",
            """
            SELECT resolution_status, COUNT(*) AS interactions,
                   ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM service_interactions), 2) AS pct
            FROM service_interactions
            GROUP BY resolution_status
            ORDER BY interactions DESC
            """)

        # =========================================================
        # CHURN ANALYSIS
        # =========================================================

        run(cursor, "15. CHURNED CUSTOMERS BY CHURN REASON",
            """
            SELECT churn_reason, COUNT(*) AS churned_customers,
                   ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM churn
                                             WHERE churn_status = 'Churned'), 2) AS pct
            FROM churn
            WHERE churn_status = 'Churned'
            GROUP BY churn_reason
            ORDER BY churned_customers DESC
            """)

        run(cursor, "16. CHURN TREND OVER TIME (monthly)",
            """
            SELECT DATE_FORMAT(churn_date, '%Y-%m') AS month,
                   COUNT(*) AS churned_customers
            FROM churn
            WHERE churn_status = 'Churned'
            GROUP BY month
            ORDER BY month
            """)

        run(cursor, "17. CHURNED CUSTOMERS BY PROVINCE",
            """
            SELECT c.province, COUNT(*) AS churned_customers,
                   ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM churn
                                             WHERE churn_status = 'Churned'), 2) AS pct
            FROM churn ch
            JOIN customers c ON c.customer_id = ch.customer_id
            WHERE ch.churn_status = 'Churned'
            GROUP BY c.province
            ORDER BY churned_customers DESC
            """)

        run(cursor, "18. RETENTION OFFER EFFECTIVENESS",
            """
            SELECT retention_attempted, retention_accepted,
                   COUNT(*) AS customers
            FROM churn
            GROUP BY retention_attempted, retention_accepted
            ORDER BY retention_attempted DESC, retention_accepted DESC
            """)

        run(cursor, "19. HIGH-LEVEL KPI SUMMARY",
            """
            SELECT
                (SELECT COUNT(*) FROM customers) AS total_customers,
                (SELECT COUNT(*) FROM subscriptions) AS total_subscriptions,
                (SELECT COUNT(*) FROM churn WHERE churn_status='Churned') AS total_churned,
                (SELECT ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM customers), 2)
                 FROM churn WHERE churn_status='Churned') AS overall_churn_rate_pct,
                (SELECT ROUND(SUM(amount), 2) FROM payments
                 WHERE payment_status IN ('Paid','Completed','Success')) AS total_revenue,
                (SELECT ROUND(AVG(amount), 2) FROM payments
                 WHERE payment_status IN ('Paid','Completed','Success')) AS avg_payment,
                (SELECT COUNT(*) FROM network_incidents) AS total_incidents,
                (SELECT ROUND(AVG(resolution_time_hours), 2)
                 FROM service_interactions) AS avg_resolution_hours
            """)

        print("\n" + "=" * 70)
        print("END OF REPORT — COPY EVERYTHING ABOVE AND PASTE BACK")
        print("=" * 70)

    except Error as e:
        print(f"MySQL Error: {e}")

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


if __name__ == "__main__":
    main()