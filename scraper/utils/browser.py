import asyncio
from playwright.async_api import async_playwright
from scraper.sources.scraper_config import SCRAPER_SETTINGS


class BrowserFactory:
    def __init__(self, headless=True):
        self.headless = headless
        self.browser = None
        self.page = None
        self.pw = None

    async def __aenter__(self):
        self.pw = await async_playwright().start()

        self.browser = await self.pw.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-web-security",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = await self.browser.new_context(
            viewport=SCRAPER_SETTINGS["VIEWPORT"],
            java_script_enabled=True,
            bypass_csp=True,
            locale=SCRAPER_SETTINGS["LOCALE"],
            timezone_id=SCRAPER_SETTINGS["TIMEZONE"],
        )

        self.page = await context.new_page()
        return self.page

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if self.browser:
                await self.browser.close()
            if self.pw:
                await self.pw.stop()
        except:
            pass
