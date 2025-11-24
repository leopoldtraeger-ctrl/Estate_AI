from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import asyncio

from scraper.sources.rightmove_scraper import fetch_links, scrape_expose
from database.ingest import save_listing

def run_scraper():
    async def task():
        links = await fetch_links(max_pages=1)
        if not links:
            return

        first = links[0]
        data = await scrape_expose(first)
        save_listing(data)

    asyncio.run(task())


with DAG(
    dag_id="estateai_daily_scraper",
    start_date=datetime(2024, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    tags=["estate", "scraper"],
) as dag:

    scrape_task = PythonOperator(
        task_id="run_scraper",
        python_callable=run_scraper,
    )
