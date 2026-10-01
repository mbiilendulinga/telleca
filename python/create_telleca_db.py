import mysql.connector
from mysql.connector import Error

DB_NAME = "telleca"

# MySQL credentials

MYSQL_HOST = "localhost"
MYSQL_USER = "root"
MYSQL_PASSWORD = "password"

def create_database():
    connection = None
    cursor = None


try:
    # Connect to MySQL server without selecting a database
    connection = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD
    )

    cursor = connection.cursor()

    # ---------------------------------------------------------
    # CREATE DATABASE
    # ---------------------------------------------------------
    cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`"
    )

    print(f"Database '{DB_NAME}' created successfully.")

    # Select database
    cursor.execute(f"USE `{DB_NAME}`")

    # ---------------------------------------------------------
    # 1. PLANS
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            plan_id INT PRIMARY KEY,
            plan_name VARCHAR(100) NOT NULL,
            plan_type VARCHAR(50) NOT NULL,
            contract_type VARCHAR(30) NOT NULL,
            monthly_fee DECIMAL(10,2) NOT NULL,
            data_allowance_gb DECIMAL(10,2) NOT NULL,
            voice_minutes INT NOT NULL,
            sms_allowance INT NOT NULL,
            plan_status VARCHAR(20) NOT NULL
        )
    """)

    # ---------------------------------------------------------
    # 2. CUSTOMERS
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INT PRIMARY KEY,
            gender VARCHAR(20) NOT NULL,
            date_of_birth DATE NOT NULL,
            province VARCHAR(50) NOT NULL,
            city VARCHAR(50) NOT NULL,
            customer_type VARCHAR(30) NOT NULL,
            acquisition_channel VARCHAR(30) NOT NULL,
            registration_date DATE NOT NULL,
            customer_status VARCHAR(20) NOT NULL
        )
    """)

    # ---------------------------------------------------------
    # 3. SUBSCRIPTIONS
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            subscription_id INT PRIMARY KEY,
            customer_id INT NOT NULL,
            plan_id INT NOT NULL,

            start_date DATE NOT NULL,
            end_date DATE,

            subscription_status VARCHAR(20) NOT NULL,
            billing_cycle VARCHAR(20) NOT NULL,

            upgrade_count INT DEFAULT 0,
            downgrade_count INT DEFAULT 0,

            FOREIGN KEY (customer_id)
                REFERENCES customers(customer_id),

            FOREIGN KEY (plan_id)
                REFERENCES plans(plan_id)
        )
    """)

    # ---------------------------------------------------------
    # 4. NETWORK INCIDENTS
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS network_incidents (
            incident_id INT PRIMARY KEY,

            incident_date DATE NOT NULL,

            province VARCHAR(50) NOT NULL,
            city VARCHAR(50) NOT NULL,

            incident_type VARCHAR(50) NOT NULL,
            severity VARCHAR(20) NOT NULL,

            duration_minutes INT NOT NULL,
            affected_customers INT NOT NULL,

            resolved BOOLEAN NOT NULL,
            resolution_time_hours DECIMAL(8,2)
        )
    """)

    # ---------------------------------------------------------
    # 5. USAGE DATA
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usage_data (
            usage_id BIGINT PRIMARY KEY,

            customer_id INT NOT NULL,
            usage_month DATE NOT NULL,

            data_used_gb DECIMAL(10,2) NOT NULL,
            voice_minutes_used INT NOT NULL,
            sms_sent INT NOT NULL,

            international_minutes INT NOT NULL,
            roaming_days INT NOT NULL,

            FOREIGN KEY (customer_id)
                REFERENCES customers(customer_id)
        )
    """)

    # ---------------------------------------------------------
    # 6. PAYMENTS
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            payment_id BIGINT PRIMARY KEY,

            customer_id INT NOT NULL,
            payment_date DATE NOT NULL,

            invoice_amount DECIMAL(10,2) NOT NULL,
            amount DECIMAL(10,2) NOT NULL,

            payment_method VARCHAR(30) NOT NULL,
            payment_status VARCHAR(20) NOT NULL,

            days_late INT NOT NULL,

            FOREIGN KEY (customer_id)
                REFERENCES customers(customer_id)
        )
    """)

    # ---------------------------------------------------------
    # 7. SERVICE INTERACTIONS
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS service_interactions (
            interaction_id BIGINT PRIMARY KEY,

            customer_id INT NOT NULL,
            interaction_date DATE NOT NULL,

            interaction_type VARCHAR(40) NOT NULL,
            issue_category VARCHAR(40) NOT NULL,
            channel VARCHAR(30) NOT NULL,

            resolution_status VARCHAR(30) NOT NULL,
            resolution_time_hours DECIMAL(8,2) NOT NULL,

            customer_satisfaction INT,

            FOREIGN KEY (customer_id)
                REFERENCES customers(customer_id)
        )
    """)

    # ---------------------------------------------------------
    # 8. CHURN
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS churn (
            churn_id INT PRIMARY KEY,

            customer_id INT NOT NULL,

            churn_status VARCHAR(20) NOT NULL,
            churn_date DATE,

            churn_reason VARCHAR(50),
            churn_channel VARCHAR(30),

            retention_attempted BOOLEAN NOT NULL,
            retention_offer VARCHAR(50),
            retention_accepted BOOLEAN,

            FOREIGN KEY (customer_id)
                REFERENCES customers(customer_id)
        )
    """)

    # ---------------------------------------------------------
    # INDEXES
    # ---------------------------------------------------------
    indexes = [

        # Subscriptions
        """
        CREATE INDEX idx_subscriptions_customer
        ON subscriptions(customer_id)
        """,

        """
        CREATE INDEX idx_subscriptions_plan
        ON subscriptions(plan_id)
        """,

        """
        CREATE INDEX idx_subscriptions_start_date
        ON subscriptions(start_date)
        """,

        # Network incidents
        """
        CREATE INDEX idx_network_incidents_date
        ON network_incidents(incident_date)
        """,

        """
        CREATE INDEX idx_network_incidents_location
        ON network_incidents(province, city)
        """,

        # Usage
        """
        CREATE INDEX idx_usage_customer
        ON usage_data(customer_id)
        """,

        """
        CREATE INDEX idx_usage_month
        ON usage_data(usage_month)
        """,

        # Payments
        """
        CREATE INDEX idx_payments_customer
        ON payments(customer_id)
        """,

        """
        CREATE INDEX idx_payments_date
        ON payments(payment_date)
        """,

        # Service interactions
        """
        CREATE INDEX idx_service_customer
        ON service_interactions(customer_id)
        """,

        """
        CREATE INDEX idx_service_date
        ON service_interactions(interaction_date)
        """,

        # Churn
        """
        CREATE INDEX idx_churn_customer
        ON churn(customer_id)
        """,

        """
        CREATE INDEX idx_churn_date
        ON churn(churn_date)
        """
    ]

    for index_sql in indexes:
        try:
            cursor.execute(index_sql)

        except mysql.connector.Error as e:
            # Ignore "index already exists" errors
            if e.errno != 1061:
                raise

    connection.commit()

    # ---------------------------------------------------------
    # SUCCESS MESSAGE
    # ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("TELLECA DATABASE CREATED SUCCESSFULLY")
    print("=" * 60)

    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()

    print(f"\nTables created: {len(tables)}\n")

    for table in tables:
        print(f"  ✓ {table[0]}")

    # ---------------------------------------------------------
    # KEY RELATIONSHIPS
    # ---------------------------------------------------------
    print("\nKey relationships:")

    print("  plans ───────────────► subscriptions")
    print("  customers ───────────► subscriptions")
    print("  customers ───────────► usage_data")
    print("  customers ───────────► payments")
    print("  customers ───────────► service_interactions")
    print("  customers ───────────► churn")

    print("\nNetwork incidents are analysed using:")
    print("  province")
    print("  city")
    print("  incident_date")

    print("\nDate fields:")
    print("  customers.registration_date")
    print("  subscriptions.start_date")
    print("  subscriptions.end_date")
    print("  network_incidents.incident_date")
    print("  usage_data.usage_month")
    print("  payments.payment_date")
    print("  service_interactions.interaction_date")
    print("  churn.churn_date")

    print("\nDatabase is ready for data generation.")

except Error as e:
    print(f"\nMySQL Error: {e}")

finally:
    if cursor:
        cursor.close()

    if connection and connection.is_connected():
        connection.close()


if __name__ == "__main__":
    create_database()
