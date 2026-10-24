import asyncio
import json
import os
import random
import sys
import argparse
from typing import Optional, Dict, List
from playwright.async_api import async_playwright, BrowserContext, Page

# Webshare Default Configurations (fallback if data/proxies.json is not present)
DEFAULT_PROXY_SERVER = "http://p.webshare.io:80"
DEFAULT_PROXY_USER_BASE = "mukul123456"
DEFAULT_PROXY_PASS = "AB123ab1234"

# Default cookies export file (optional secondary import)
DEFAULT_COOKIES_FILE = "cookies.json"

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


def resolve_profile_path(profile_name_or_path: str = "default") -> str:
    """
    Resolves a profile name into its folder directory path:
    - If a path is provided (e.g. './custom_dir' or 'C:/...'), returns that path.
    - If 'default' and the existing './browser_profile' folder exists, reuses it.
    - Otherwise, isolates each profile cleanly inside 'browser_profiles/<name>'.
    """
    if not profile_name_or_path or profile_name_or_path == "default":
        if os.path.exists("./browser_profile"):
            return "./browser_profile"
        return os.path.join("browser_profiles", "default")

    if os.path.sep in profile_name_or_path or "/" in profile_name_or_path or "\\" in profile_name_or_path:
        return profile_name_or_path

    return os.path.join("browser_profiles", profile_name_or_path)


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


def sanitize_cookie_for_playwright(raw_cookie: dict) -> Optional[dict]:
    """
    Cleans and normalizes a single cookie object (from Cookie-Editor / EditThisCookie)
    into the format strictly expected by Playwright.
    """
    cookie = {}

    if "name" in raw_cookie and "value" in raw_cookie:
        cookie["name"] = str(raw_cookie["name"])
        cookie["value"] = str(raw_cookie["value"])
    else:
        return None

    if "domain" in raw_cookie and raw_cookie["domain"]:
        cookie["domain"] = raw_cookie["domain"]
    if "path" in raw_cookie and raw_cookie["path"]:
        cookie["path"] = raw_cookie["path"]
    if "url" in raw_cookie and raw_cookie["url"]:
        cookie["url"] = raw_cookie["url"]

    if "domain" not in cookie and "url" not in cookie:
        return None

    if "expires" in raw_cookie and raw_cookie["expires"] is not None:
        cookie["expires"] = float(raw_cookie["expires"])
    elif "expirationDate" in raw_cookie and raw_cookie["expirationDate"] is not None:
        if not raw_cookie.get("session", False):
            cookie["expires"] = float(raw_cookie["expirationDate"])

    if "httpOnly" in raw_cookie:
        cookie["httpOnly"] = bool(raw_cookie["httpOnly"])
    if "secure" in raw_cookie:
        cookie["secure"] = bool(raw_cookie["secure"])

    if "sameSite" in raw_cookie and raw_cookie["sameSite"]:
        s_site = str(raw_cookie["sameSite"]).lower()
        if s_site in ["strict"]:
            cookie["sameSite"] = "Strict"
        elif s_site in ["lax", "unspecified"]:
            cookie["sameSite"] = "Lax"
        elif s_site in ["none", "no_restriction"]:
            cookie["sameSite"] = "None"

    return cookie


def load_and_sanitize_cookies(filepath: str = DEFAULT_COOKIES_FILE) -> List[dict]:
    """Loads exported cookies from a JSON file and returns sanitized cookies."""
    if not os.path.exists(filepath):
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw_cookies = json.load(f)

        if not isinstance(raw_cookies, list):
            return []

        sanitized = []
        for c in raw_cookies:
            clean = sanitize_cookie_for_playwright(c)
            if clean:
                sanitized.append(clean)

        return sanitized
    except Exception as e:
        print(f"[!] Error loading cookies from '{filepath}': {e}")
        return []


class WebshareScrapper:
    """
    Stealth Playwright scraper supporting isolated Persistent Profiles.
    
    Features:
    - Multiple Isolated Profiles: Each profile gets its own storage folder
      where cookies, logins, localStorage, and IndexedDB persist independently.
    - Real Google Chrome channel or Firefox support to avoid bot flags.
    - Automation flags disabled (--disable-blink-features=AutomationControlled).
    - Stealth scripts injected to mask navigator.webdriver.
    - Webshare proxy integration.
    """

    def __init__(
        self,
        headless: bool = False,
        browser_type: str = "chrome",  # Options: 'chrome', 'firefox', 'chromium'
        profile: str = "default",       # Profile name or directory path
        proxy_config: Optional[Dict[str, str]] = None,
        cookies_file: Optional[str] = DEFAULT_COOKIES_FILE
    ):
        self.headless = headless
        self.browser_type_name = browser_type.lower()
        self.user_data_dir = os.path.abspath(resolve_profile_path(profile))
        self.proxy_config = proxy_config or get_webshare_proxy()
        self.cookies_file = cookies_file
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def start(self) -> Page:
        """Launches the persistent anti-detect proxied browser for this profile."""
        print(f"[*] Active Profile Folder: {self.user_data_dir}")
        print(f"[*] Starting browser engine [{self.browser_type_name}] with proxy: {self.proxy_config.get('server')}")
        
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.playwright = await async_playwright().start()

        common_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--lang=en-US",
        ]

        if self.browser_type_name == "chrome":
            # Launch persistent context using system Google Chrome
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                channel="chrome",
                headless=self.headless,
                proxy=self.proxy_config,
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                timezone_id="America/New_York",
                ignore_default_args=["--enable-automation"],
                args=common_args
            )
        elif self.browser_type_name == "firefox":
            # Launch persistent context using Firefox
            self.context = await self.playwright.firefox.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=self.headless,
                proxy=self.proxy_config,
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                timezone_id="America/New_York",
                firefox_user_prefs={
                    "dom.webdriver.enabled": False,
                    "useAutomationExtension": False
                }
            )
        else:
            # Fallback to persistent Chromium
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=self.headless,
                proxy=self.proxy_config,
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                timezone_id="America/New_York",
                ignore_default_args=["--enable-automation"],
                args=common_args
            )

        # Inject anti-detection stealth script on all pages and frames
        await self.context.add_init_script(STEALTH_INIT_SCRIPT)

        # Optional: load external cookies.json if present
        if self.cookies_file and os.path.exists(self.cookies_file):
            await self.inject_cookies(self.cookies_file)

        # In persistent context, the initial page is automatically created
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        return self.page

    async def inject_cookies(self, filepath: str = DEFAULT_COOKIES_FILE) -> int:
        """Injects cookies from a JSON file into the profile context if needed."""
        if not self.context:
            raise RuntimeError("Browser context not started yet.")

        cookies = load_and_sanitize_cookies(filepath)
        if cookies:
            try:
                await self.context.add_cookies(cookies)
                print(f"[+] Loaded {len(cookies)} cookies into profile from '{filepath}'")
                return len(cookies)
            except Exception as e:
                print(f"[!] Cookie import warning: {e}")
        return 0

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
        print(f"\n[*] Browser is open and ready under profile: [{os.path.basename(self.user_data_dir)}]")
        print("[*] All logins, cookies, and actions are saved automatically.")
        print("[*] Close the browser window when finished to save and exit.")
        close_event = asyncio.Event()

        if self.page:
            self.page.on("close", lambda _: close_event.set())
        if self.context:
            self.context.on("close", lambda _: close_event.set())

        try:
            await close_event.wait()
            print("[*] Browser window was closed by user.")
        except asyncio.CancelledError:
            pass

    async def close(self):
        """Clean up and save profile state."""
        try:
            if self.context:
                await self.context.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        print(f"[*] Browser closed cleanly. Session saved in '{self.user_data_dir}'.")


def parse_cli_args():
    """Parses command-line arguments for browser and profile selection."""
    parser = argparse.ArgumentParser(description="Webshare Playwright Persistent Profile Scraper")
    parser.add_argument(
        "--profile", "-p",
        default="default",
        help="Profile name or folder path (e.g. 'profile1', 'account2', 'profile_google')"
    )
    parser.add_argument(
        "--browser", "-b",
        choices=["chrome", "firefox", "chromium"],
        default="chrome",
        help="Browser engine to launch (default: chrome)"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in background headless mode"
    )
    parser.add_argument(
        "positional_args",
        nargs="*",
        help="Convenience positional arguments: [browser] [profile] or just [profile]"
    )

    args = parser.parse_args()

    # Handle convenience positional arguments (e.g. `python Scrapper.py profile2` or `python Scrapper.py firefox profile2`)
    if args.positional_args:
        pos0 = args.positional_args[0].lower()
        if pos0 in ["chrome", "firefox", "chromium"]:
            args.browser = pos0
            if len(args.positional_args) > 1:
                args.profile = args.positional_args[1]
        else:
            args.profile = args.positional_args[0]

    return args


async def main():
    cli_args = parse_cli_args()

    # Initialize scraper with chosen Persistent Profile and Browser
    scrapper = WebshareScrapper(
        headless=cli_args.headless,
        browser_type=cli_args.browser,
        profile=cli_args.profile
    )
    
    try:
        page = await scrapper.start()
        
        # 1. Verify proxy IP
        await scrapper.verify_proxy_ip()
        
        # 2. Example: Navigate to target website
        # Replace this URL with your target website
        target_url = "https://www.linkedin.com/feed/"
        await page.goto(target_url, wait_until="domcontentloaded")
        print("Page Title:", await page.title())

        # Keep browser open until manually closed by user
        await scrapper.wait_until_closed()

    except KeyboardInterrupt:
        print("\n[*] Script interrupted by user.")
    finally:
        await scrapper.close()


if __name__ == "__main__":
    asyncio.run(main())
