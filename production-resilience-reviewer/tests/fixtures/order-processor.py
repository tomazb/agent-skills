"""
Test fixture: order-processor.py

An order-processing consumer with multiple intentional resilience gaps,
designed to exercise the production-resilience-reviewer skill across
several failure lenses.

Known issues (for skill verification):
  - No DLQ or poison-message handling (Lens 5: Retry & Backpressure)
  - Inventory deduction retried without idempotency key (Lens 5)
  - Three-layer retry chain (order → inventory → warehouse) (Lens 5)
  - Schema migration drops column without backward-compat transition (Lens 8: Change Management)
  - Single-region write; no RPO/RTO defined (Lens 9: Disaster Recovery)
  - No rate-limiting on inbound order intake (Lens 10: Security & Abuse)
"""

import boto3
import requests


def process_order(message: dict) -> None:
    order_id = message["order_id"]
    items = message["items"]

    for item in items:
        # Retries without idempotency key — duplicate deductions possible
        for attempt in range(3):
            resp = requests.post(
                "https://inventory-service/deduct",
                json={"sku": item["sku"], "qty": item["qty"]},
            )
            if resp.status_code == 200:
                break

    # Publishes to warehouse — no DLQ if warehouse is down
    sqs = boto3.client("sqs", region_name="us-east-1")
    sqs.send_message(
        QueueUrl="https://sqs.us-east-1.amazonaws.com/YOUR_ACCOUNT_ID/warehouse",
        MessageBody=str({"order_id": order_id, "items": items}),
    )
