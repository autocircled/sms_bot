import asyncio
import json
import os
import random
from typing import Optional, Dict
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# Webshare Default Configurations (fallback if data/proxies.json is not present)
DEFAULT_PROXY_SERVER = "http://p.webshare.io:80"
DEFAULT_PROXY_USER_BASE = "mukul123456-1"
DEFAULT_PROXY_PASS = "AB123ab1234"


def parse_proxy_string(proxy_str: str) -> Dict[str, str]:
    """
    Parses a proxy string in standard format:
    'host:port:username:password' or 'http://host:port:username:password'
    """
    cleaned = proxy_str.replace("http://", "").replace("https://", "").strip()
    parts = cleaned.split(":")
    
    if len(parts) == 4:
        host, port, user, pwd = parts
        return {
            "server": f"http://{host}:{port}",
            "username": user,
            "password": pwd
        }
    elif len(parts) == 2:
        host, port = parts
        return {
            "server": f"http://{host}:{port}"
        }
    else:
        raise ValueError(f"Invalid proxy format: {proxy_str}. Expected host:port:user:pass")


def load_proxy_from_file(filepath: str = "data/proxies.json") -> Optional[Dict[str, str]]:
    """Loads a proxy from the proxies.json file if available."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            proxies = data.get("proxies", [])
            if proxies:
                selected = random.choice(proxies)
                return parse_proxy_string(selected)
        except Exception as e:
            print(f"[!] Warning reading {filepath}: {e}")
    return None


def get_webshare_proxy(rotate: bool = True) -> Dict[str, str]:
    """
    Returns a Webshare proxy configuration dictionary for Playwright.
    Prioritizes data/proxies.json; falls back to rotating sub-user credentials.
    """
    file_proxy = load_proxy_from_file()
    if file_proxy:
        return file_proxy

    # Fallback to direct credentials with random port/sub-user index
    sub_user = f"{DEFAULT_PROXY_USER_BASE}-{random.randint(1, 100)}" if rotate else DEFAULT_PROXY_USER_BASE
    return {
        "server": DEFAULT_PROXY_SERVER,
        "username": sub_user,
        "password": DEFAULT_PROXY_PASS,
    }


class WebshareScrapper:
    """
    Playwright-based web scraper configured with Webshare proxy support.
    """

    def __init__(
        self,
        headless: bool = False,
        browser_type: str = "chromium",
        proxy_config: Optional[Dict[str, str]] = None
    ):
        self.headless = headless
        self.browser_type_name = browser_type
        self.proxy_config = proxy_config or get_webshare_proxy()
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def start(self) -> Page:
        """Launches the proxied browser and initializes context and page."""
        print(f"[*] Starting browser ({self.browser_type_name}) with proxy: {self.proxy_config.get('server')}")
        self.playwright = await async_playwright().start()

        browser_engine = getattr(self.playwright, self.browser_type_name)

        # Launch browser with proxy routing
        self.browser = await browser_engine.launch(
            headless=self.headless,
            proxy=self.proxy_config,
            args=["--disable-blink-features=AutomationControlled"]
        )

        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        self.page = await self.context.new_page()
        return self.page

    async def verify_proxy_ip(self) -> str:
        """Navigates to an IP check service and prints the detected outbound IP."""
        if not self.page:
            raise RuntimeError("Browser not started. Call start() first.")

        print("[*] Verifying current proxy IP address...")
        try:
            await self.page.goto("https://ipv4.webshare.io/", timeout=30000)
            ip_address = (await self.page.locator("body").inner_text()).strip()
            print(f"[+] Connected successfully! Outbound Proxy IP: {ip_address}")
            return ip_address
        except Exception as e:
            print(f"[-] Webshare IP check failed: {e}. Trying httpbin...")
            await self.page.goto("https://httpbin.org/ip", timeout=30000)
            ip_content = await self.page.locator("body").inner_text()
            print(f"[+] Outbound IP response: {ip_content.strip()}")
            return ip_content.strip()

    async def close(self):
        """Clean up and close all browser resources."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print("[*] Browser closed cleanly.")


async def main():
    # Initialize the proxied scraper (set headless=False to observe the browser)
    scrapper = WebshareScrapper(headless=False, browser_type="chromium")
    
    try:
        page = await scrapper.start()
        
        # 1. Verify proxy IP
        await scrapper.verify_proxy_ip()
        
        # 2. Example: Navigate to target website
        # await page.goto("https://example.com", wait_until="domcontentloaded")
        # print("Page Title:", await page.title())

        # Wait a moment before exit (useful when headless=False)
        await asyncio.sleep(5)

    finally:
        await scrapper.close()


if __name__ == "__main__":
    asyncio.run(main())
