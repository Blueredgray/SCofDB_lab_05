"""
Locust template for LAB 05 RPS measurements.

Run:
locust -f loadtest/locustfile.py --host=http://localhost:8082
"""

from locust import HttpUser, task, between


# Замените ORDER_ID_HERE на UUID существующего заказа
ORDER_ID = "ORDER_ID_HERE"


class CacheUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(3)
    def get_catalog(self):
        self.client.get("/api/cache-demo/catalog?use_cache=true")

    @task(2)
    def get_order_card(self):
        self.client.get(f"/api/cache-demo/orders/{ORDER_ID}/card?use_cache=true")
