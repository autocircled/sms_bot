import asyncio
import json
import os
import random
import sys
import argparse
from typing import Optional, Dict, List, Any
from playwright.async_api import async_playwright, BrowserContext, Page

# Default files
DEFAULT_URLS_FILE = "urls.txt"
DEFAULT_OUTPUT_FILE = "scraped_jobs.json"
DEFAULT_PROXIES_FILE = "data/proxies.json"

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


def load_proxy_from_file(filepath: str = DEFAULT_PROXIES_FILE) -> Optional[Dict[str, str]]:
    """Loads a proxy from a JSON file if available."""
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


def get_webshare_proxy() -> Optional[Dict[str, str]]:
    """
    Returns proxy configuration.
    Priority:
    1. Local data/proxies.json file
    2. Environment variables PROXY_SERVER, PROXY_USER, PROXY_PASS
    3. Returns None if unconfigured (direct connection)
    """
    file_proxy = load_proxy_from_file()
    if file_proxy:
        return file_proxy

    # Check environment variables
    env_server = os.getenv("PROXY_SERVER")
    if env_server:
        conf = {"server": env_server}
        user = os.getenv("PROXY_USER")
        pwd = os.getenv("PROXY_PASS")
        if user and pwd:
            conf["username"] = user
            conf["password"] = pwd
        return conf

    return None


def load_job_urls(filepath: str = DEFAULT_URLS_FILE) -> List[str]:
    """
    Loads target job URLs from a text file (one URL per line).
    Falls back to the provided default list if the file is not found.
    """
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
            if urls:
                return urls
        except Exception as e:
            print(f"[!] Error reading URLs from '{filepath}': {e}")

    # Default URLs fallback
    return [
        "https://www.dinjob.com/job/customer-service-associate-mv72gy9j-u582",
        "https://www.dinjob.com/job/general-manager-mv71i1sm-5jru",
        "https://www.dinjob.com/job/insurance-regulatory-and-compliance-associate-mv7115s4-0e4m",
        "https://www.dinjob.com/job/retail-sales-supervisor-mv7026m6-beb9",
    ]


class WebshareScrapper:
    """
    Stealth Playwright scraper supporting:
    - Batch job page scraping for schema.org application/ld+json data
    - Multiple Isolated Profiles: Each profile keeps its cookies/logins separately on disk
    - Real Google Chrome channel or Firefox support to avoid bot flags
    - Automation flags disabled (--disable-blink-features=AutomationControlled)
    - Stealth scripts injected to mask navigator.webdriver
    - Optional proxy routing via data/proxies.json or environment variables
    """

    def __init__(
        self,
        headless: bool = False,
        browser_type: str = "chrome",  # Options: 'chrome', 'firefox', 'chromium'
        profile: str = "default",       # Profile name or directory path
        proxy_config: Optional[Dict[str, str]] = None
    ):
        self.headless = headless
        self.browser_type_name = browser_type.lower()
        self.user_data_dir = os.path.abspath(resolve_profile_path(profile))
        self.proxy_config = proxy_config or get_webshare_proxy()
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def start(self) -> Page:
        """Launches the persistent anti-detect browser for this profile."""
        print(f"[*] Active Profile Folder: {self.user_data_dir}")
        proxy_display = self.proxy_config.get("server") if self.proxy_config else "Direct (no proxy)"
        print(f"[*] Starting browser engine [{self.browser_type_name}] | Proxy: {proxy_display}")
        
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.playwright = await async_playwright().start()

        common_args = [
            "--disable-blink-features=AutomationControlled",
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

        # In persistent context, the initial page is automatically created
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        return self.page

    async def verify_proxy_ip(self) -> str:
        """Navigates to an IP check service and prints the detected outbound IP."""
        if not self.page:
            raise RuntimeError("Browser not started. Call start() first.")

        print("[*] Checking current outbound IP address...")
        try:
            await self.page.goto("https://ipv4.webshare.io/", timeout=30000)
            ip_address = (await self.page.locator("body").inner_text()).strip()
            print(f"[+] Outbound IP: {ip_address}")
            return ip_address
        except Exception as e:
            print(f"[-] Webshare IP check failed: {e}. Trying httpbin...")
            await self.page.goto("https://httpbin.org/ip", timeout=30000)
            ip_content = await self.page.locator("body").inner_text()
            print(f"[+] Outbound IP response: {ip_content.strip()}")
            return ip_content.strip()

    async def extract_ld_json(self, url: str) -> List[Dict[str, Any]]:
        """
        Visits a single page and extracts all application/ld+json script contents.
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start() first.")

        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)

        # Allow dynamic frameworks a moment to populate metadata
        try:
            await self.page.wait_for_selector('script[type="application/ld+json"]', timeout=8000)
        except Exception:
            pass

        scripts = await self.page.locator('script[type="application/ld+json"]').all()
        extracted: List[Dict[str, Any]] = []

        for s in scripts:
            try:
                raw_text = (await s.inner_text()).strip()
                if not raw_text:
                    continue
                parsed = json.loads(raw_text)

                # Check if it's an array or single dict or @graph structure
                if isinstance(parsed, list):
                    extracted.extend([item for item in parsed if isinstance(item, dict)])
                elif isinstance(parsed, dict):
                    if "@graph" in parsed and isinstance(parsed["@graph"], list):
                        extracted.extend([item for item in parsed["@graph"] if isinstance(item, dict)])
                    else:
                        extracted.append(parsed)
            except Exception as e:
                print(f"    [!] Error parsing ld+json tag: {e}")

        return extracted

    async def scrape_jobs_batch(
        self,
        urls: List[str],
        output_file: str = DEFAULT_OUTPUT_FILE,
        delay_range: tuple = (1.0, 2.5)
    ) -> List[Dict[str, Any]]:
        """
        Visits each URL in the list, extracts the schema.org application/ld+json,
        and saves all collected jobs into a single JSON array.
        """
        results: List[Dict[str, Any]] = []
        total = len(urls)
        print(f"\n{'='*70}")
        print(f"[*] Starting Batch Extraction: {total} job URL(s)")
        print(f"{'='*70}")

        for index, url in enumerate(urls, start=1):
            url = url.strip()
            if not url or url.startswith("#"):
                continue

            print(f"\n[{index}/{total}] Visiting: {url}")
            try:
                ld_items = await self.extract_ld_json(url)

                # Look for schema with @type == "JobPosting"
                job_postings = [
                    item for item in ld_items 
                    if str(item.get("@type", "")).lower() == "jobposting"
                ]

                if job_postings:
                    for job in job_postings:
                        job["_scraped_url"] = url
                        results.append(job)
                        title = job.get("title", "N/A")
                        hiring_org = job.get("hiringOrganization")
                        org_name = hiring_org.get("name", "N/A") if isinstance(hiring_org, dict) else str(hiring_org or "N/A")
                        print(f"    [+] Found JobPosting: '{title}' by '{org_name}'")
                elif ld_items:
                    # If specific JobPosting type is not explicitly labeled, save all ld+json blocks
                    for item in ld_items:
                        item["_scraped_url"] = url
                        results.append(item)
                    print(f"    [+] Saved {len(ld_items)} application/ld+json object(s)")
                else:
                    print("    [-] No application/ld+json found on page.")

                # Periodically save incremental progress so data is not lost
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)

            except Exception as e:
                print(f"    [!] Error processing {url}: {e}")

            # Polite anti-ban delay between page requests
            if index < total:
                wait_time = random.uniform(*delay_range)
                await asyncio.sleep(wait_time)

        print(f"\n{'='*70}")
        print(f"[✓] Completed! Successfully scraped {len(results)} job schema(s).")
        print(f"[✓] Saved results to: {os.path.abspath(output_file)}")
        print(f"{'='*70}")
        return results

    async def wait_until_closed(self):
        """
        Keeps the script running and the browser open until you manually
        close the browser window or press Ctrl+C in the terminal.
        """
        print(f"\n[*] Browser is open under profile: [{os.path.basename(self.user_data_dir)}]")
        print("[*] Close the browser window when finished to exit.")
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
    """Parses command-line arguments for browser, profile, and scraping inputs."""
    parser = argparse.ArgumentParser(description="Webshare Playwright Job Schema Scraper")
    parser.add_argument(
        "--profile", "-p",
        default="default",
        help="Profile name or folder path (e.g. 'profile1', 'account2', 'default')"
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
        "--urls-file", "-u",
        default=DEFAULT_URLS_FILE,
        help=f"Path to text file containing job URLs, one per line (default: {DEFAULT_URLS_FILE})"
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT_FILE,
        help=f"Output JSON file path (default: {DEFAULT_OUTPUT_FILE})"
    )
    parser.add_argument(
        "--skip-ip-check",
        action="store_true",
        help="Skip the initial proxy IP verification check"
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

    # 1. Load job URLs to scrape
    job_urls = load_job_urls(cli_args.urls_file)
    print(f"[*] Loaded {len(job_urls)} URL(s) from '{cli_args.urls_file}'.")

    # 2. Initialize scraper with chosen Persistent Profile and Browser
    scrapper = WebshareScrapper(
        headless=cli_args.headless,
        browser_type=cli_args.browser,
        profile=cli_args.profile
    )
    
    try:
        await scrapper.start()
        
        # Check outbound IP
        if not cli_args.skip_ip_check:
            await scrapper.verify_proxy_ip()
        
        # 3. Scrape application/ld+json for each job URL and output to JSON
        await scrapper.scrape_jobs_batch(
            urls=job_urls,
            output_file=cli_args.output
        )

        # Keep browser open if user is running headfully to inspect
        if not cli_args.headless:
            await scrapper.wait_until_closed()

    except KeyboardInterrupt:
        print("\n[*] Script interrupted by user.")
    finally:
        await scrapper.close()


if __name__ == "__main__":
    asyncio.run(main())
