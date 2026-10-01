 Telleca Telecom | Customer & Churn Analysis

A Power BI business intelligence project analysing customer growth, revenue, customer behaviour and churn for a simulated telecommunications company.

The analysis covers January 2022 – September 2025.

 Project Overview

The project was built to explore how customer and operational data can be transformed into an interactive business intelligence report.

The analysis combines customer, subscription, payment, usage, service interaction, network incident and churn data.

The Power BI report is structured into three pages:

 1. Executive Summary

Provides an overview of:

 Customer growth
 Revenue performance
 Customer mix
 Subscription and plan distribution
 Revenue by province
 Overall churn

 2. Customer Behaviour

Examines:

 Customer segments
 Acquisition channels
 Plan adoption
 Data, voice and SMS usage
 Customer service interactions
 Resolution outcomes

 3. Churn Analysis

Analyses:

 Overall churn
 Churn trends
 Churn by contract type
 Churn by plan
 Churn by province
 Churn reasons
 Retention activity

 Dataset

The MySQL database contains the following tables:

```text
customers
plans
subscriptions
payments
usage_data
service_interactions
network_incidents
churn
```

The dataset contains:

 20,143 customers
 20,056 subscriptions
 4,435 recorded churn events
 6,118 network incidents

The data is synthetic and was created specifically for this portfolio project.

 Data Model

The database was designed as a relational model, with customer and subscription information connected to transactional and behavioural data.

```text
plans
   │
   ▼
subscriptions ───► customers
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
      payments     usage_data    churn
                       │
                       ▼
              service_interactions

network_incidents
```

 Technology

 Python — database creation and data preparation
 MySQL — relational database
 Power BI — data modelling, DAX and visualisation
 Git / GitHub — version control and project documentation

 Project Structure

```text
telleca/
│
├── python/
│   └── create_telleca_db.py
│
├── powerbi/
│   └── telleca_report.pbix
│
├── data/
│   └── ...
│
├── docs/
│   ├── insights.md
│   └── ...
│
└── README.md
```

 Key Metrics

| Metric                      |      Result |
| --------------------------- | ----------: |
| Customers                   |      20,143 |
| Subscriptions               |      20,056 |
| Churned customers           |       4,435 |
| Overall churn rate          |      22.02% |
| Revenue                     |  ZMW 34.49M |
| Network incidents           |       6,118 |
| Average incident resolution | 17.79 hours |

 Analysis Period

January 2022 – September 2025

Because 2025 only covers the period available in the dataset, 2025 revenue is treated as year-to-date rather than a full-year result.

 Important Data Notes

The churn table records churned customers and does not contain a separate `Retained` record for every active customer. Retention is therefore derived from the customer population and recorded churn.

There are also 87 customers without a corresponding subscription record. These records were retained rather than artificially assigning subscriptions.

 Full Analysis

Detailed findings and observations are available in [`insights.md`](docs/insights.md).

---

Portfolio Project — Data Analytics & Business Intelligence*
