import asyncio
import json
import os
import random
import sys
from typing import Optional, Dict
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# Webshare Default Configurations (fallback if data/proxies.json is not present)
DEFAULT_PROXY_SERVER = "http://p.webshare.io:80"
DEFAULT_PROXY_USER_BASE = "mukul123456"
DEFAULT_PROXY_PASS = "AB123ab1234"

# Stealth script injected before any web page scripts execute
STEALTH_INIT_SCRIPT = """
// 1. Remove navigator.webdriver automation flag
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// 2. Ensure window.chrome runtime exists (for Chromium / Chrome)
if (!window.chrome) {
    window.chrome = {
        app: {
            isInstalled: false,
            InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
            RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
        },
        runtime: {
            OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
            OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
            PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
            PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
            PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
            RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' }
        }
    };
}

// 3. Realistic navigator.plugins & languages
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});

Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en']
});

// 4. Notification permissions mock
if (window.navigator.permissions) {
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            origQuery(parameters)
    );
}
"""


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
    Stealth Playwright scraper configured with:
    - Real Google Chrome channel or Firefox support to avoid basic bot detection
    - Automation flags disabled (--disable-blink-features=AutomationControlled, ignore --enable-automation)
    - Anti-bot stealth JavaScript injected into all frames
    - Webshare proxy integration
    """

    def __init__(
        self,
        headless: bool = False,
        browser_type: str = "chrome",  # Options: 'chrome', 'firefox', 'chromium'
        proxy_config: Optional[Dict[str, str]] = None
    ):
        self.headless = headless
        self.browser_type_name = browser_type.lower()
        self.proxy_config = proxy_config or get_webshare_proxy()
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def start(self) -> Page:
        """Launches the anti-detect proxied browser."""
        print(f"[*] Starting browser engine [{self.browser_type_name}] with proxy: {self.proxy_config.get('server')}")
        self.playwright = await async_playwright().start()

        if self.browser_type_name == "chrome":
            # Launch the system's actual installed Google Chrome with stealth flags
            self.browser = await self.playwright.chromium.launch(
                channel="chrome",
                headless=self.headless,
                proxy=self.proxy_config,
                ignore_default_args=["--enable-automation"],
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--lang=en-US",
                ]
            )
        elif self.browser_type_name == "firefox":
            # Firefox naturally lacks Chromium-specific bot flags
            self.browser = await self.playwright.firefox.launch(
                headless=self.headless,
                proxy=self.proxy_config,
                firefox_user_prefs={
                    "dom.webdriver.enabled": False,
                    "useAutomationExtension": False
                }
            )
        else:  # Fallback to bundled chromium
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                proxy=self.proxy_config,
                ignore_default_args=["--enable-automation"],
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars"
                ]
            )

        # Create context without hardcoding old User-Agent strings (avoids Sec-CH-UA mismatches)
        self.context = await self.browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/New_York"
        )

        # Inject stealth evasions into every page/iframe before scripts execute
        await self.context.add_init_script(STEALTH_INIT_SCRIPT)

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

    async def wait_until_closed(self):
        """
        Keeps the script running and the browser open until you manually
        close the browser window or press Ctrl+C in the terminal.
        """
        print("\n[*] Browser is open and ready. Close the browser window to exit.")
        close_event = asyncio.Event()

        # Trigger event when user closes page, context, or browser
        if self.page:
            self.page.on("close", lambda _: close_event.set())
        if self.context:
            self.context.on("close", lambda _: close_event.set())
        if self.browser:
            self.browser.on("disconnected", lambda _: close_event.set())

        try:
            await close_event.wait()
            print("[*] Browser window was closed by user.")
        except asyncio.CancelledError:
            pass

    async def close(self):
        """Clean up and close all browser resources."""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        print("[*] Browser closed cleanly.")


async def main():
    # Detect browser choice from command line: python Scrapper.py [chrome|firefox|chromium]
    # Default is real Google Chrome
    selected_browser = "chrome"
    for arg in sys.argv[1:]:
        if arg.lower() in ["chrome", "firefox", "chromium"]:
            selected_browser = arg.lower()

    # Initialize scraper with anti-detection settings
    scrapper = WebshareScrapper(headless=False, browser_type=selected_browser)
    
    try:
        page = await scrapper.start()
        
        # 1. Verify proxy IP
        await scrapper.verify_proxy_ip()
        
        # 2. Example: Navigate to target website
        # Note: You can replace this URL with your target page
        await page.goto("https://whatismyipaddress.com/", wait_until="domcontentloaded")
        print("Page Title:", await page.title())

        # Keep browser open until manually closed by user
        await scrapper.wait_until_closed()

    except KeyboardInterrupt:
        print("\n[*] Script interrupted by user.")
    finally:
        await scrapper.close()


if __name__ == "__main__":
    asyncio.run(main())
