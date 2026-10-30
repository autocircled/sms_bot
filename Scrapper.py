import asyncio
import json
import os
import random
import sys
import argparse
import urllib.parse
import re
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


def decode_safety_url(href: str) -> Optional[str]:
    """
    Decodes the actual external destination URL from DinJob's safety redirect URL,
    and replaces source=LinkedIn with source=Dinjob.
    Example:
    https://www.dinjob.com/safety/go/?url=https%3A%2F%2Fwonder...myworkdayjobs.com%2F...%3Fsource%3DLinkedIn...
    -> https://wonder...myworkdayjobs.com/.../?source=Dinjob
    """
    if not href:
        return None
    try:
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        if "url" in qs and qs["url"]:
            raw_url = urllib.parse.unquote(qs["url"][0])
            # Replace source=LinkedIn (case-insensitive) with source=Dinjob
            cleaned_url = re.sub(r'([?&]source=)[^&#]+', r'\g<1>Dinjob', raw_url, flags=re.IGNORECASE)
            return cleaned_url
    except Exception:
        pass
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
    return []


class WebshareScrapper:
    """
    Stealth Playwright scraper supporting:
    - Batch job page scraping for schema.org application/ld+json data
    - Direct extraction and decoding of actual apply links from "Apply on Company Site"
    - Converting source=LinkedIn to source=Dinjob in actual_apply_url
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
        proxy_config: Optional[Dict[str, str]] = None,
        extensions: Optional[List[str]] = None
    ):
        self.headless = headless
        self.browser_type_name = browser_type.lower()
        self.user_data_dir = os.path.abspath(resolve_profile_path(profile))
        self.proxy_config = proxy_config or get_webshare_proxy()
        self.extensions = extensions or []
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

        # Add unpacked Chrome extensions if specified
        if self.extensions:
            if self.browser_type_name in ["chrome", "chromium"]:
                valid_exts = []
                for ext in self.extensions:
                    abs_path = os.path.abspath(ext)
                    manifest_file = os.path.join(abs_path, "manifest.json")
                    if os.path.exists(manifest_file):
                        valid_exts.append(abs_path)
                    elif os.path.exists(abs_path):
                        valid_exts.append(abs_path)
                    else:
                        print(f"[!] Warning: Extension directory not found or missing manifest.json: {ext}")

                if valid_exts:
                    joined_exts = ",".join(valid_exts)
                    common_args.append(f"--load-extension={joined_exts}")
                    print(f"[*] Loaded {len(valid_exts)} unpacked extension(s): {', '.join([os.path.basename(e) for e in valid_exts])}")
            else:
                print(f"[!] Note: Loading extensions via '--extension' is supported in Chrome/Chromium.")

        # Ignore Playwright's default flags that disable extensions and component updates
        chromium_ignore_defaults = [
            "--enable-automation",
            "--disable-extensions",
            "--disable-component-update",
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
                ignore_default_args=chromium_ignore_defaults,
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
                ignore_default_args=chromium_ignore_defaults,
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

    async def extract_apply_link(self) -> Optional[str]:
        """
        Locates the 'Apply on Company Site' link on the current DinJob page
        and extracts the decoded destination link (with source=LinkedIn changed to source=Dinjob).
        """
        if not self.page:
            return None

        candidate_selectors = [
            "a:has-text('Apply on Company Site')",
            "a[href*='/safety/go/']",
            "a[aria-label='Apply on company website']",
            "a:has-text('Apply on company')",
            "a:has-text('Apply on')",
        ]

        for sel in candidate_selectors:
            try:
                links = await self.page.locator(sel).all()
                for link in links:
                    href = await link.get_attribute("href")
                    if href and ("/safety/go/" in href or "url=" in href):
                        encoded_url = href if href.startswith("http") else urllib.parse.urljoin("https://www.dinjob.com", href)
                        actual_url = decode_safety_url(encoded_url)
                        if actual_url:
                            return actual_url
            except Exception:
                continue

        return None

    async def extract_ld_json(self) -> List[Dict[str, Any]]:
        """
        Extracts all application/ld+json script contents from the currently loaded page.
        """
        if not self.page:
            return []

        # Allow dynamic frameworks a moment to populate metadata
        try:
            await self.page.wait_for_selector('script[type="application/ld+json"]', timeout=6000)
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
        extracts the actual apply link from 'Apply on Company Site' (with source=Dinjob),
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
                # 1. Navigate to the job page
                await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)

                # 2. Extract schema.org metadata
                ld_items = await self.extract_ld_json()

                # 3. Extract and decode the actual Apply link (with source=LinkedIn -> source=Dinjob)
                actual_apply = await self.extract_apply_link()

                # Look for schema with @type == "JobPosting"
                job_postings = [
                    item for item in ld_items 
                    if str(item.get("@type", "")).lower() == "jobposting"
                ]

                if job_postings:
                    for job in job_postings:
                        job["_scraped_url"] = url
                        job["actual_apply_url"] = actual_apply

                        results.append(job)

                        title = job.get("title", "N/A")
                        hiring_org = job.get("hiringOrganization")
                        org_name = hiring_org.get("name", "N/A") if isinstance(hiring_org, dict) else str(hiring_org or "N/A")
                        print(f"    [+] Job: '{title}' by '{org_name}'")
                        if actual_apply:
                            print(f"    [+] Apply Link: {actual_apply}")
                        else:
                            print(f"    [*] Apply Link: None (Internal or Sign-in required)")
                elif ld_items:
                    for item in ld_items:
                        item["_scraped_url"] = url
                        item["actual_apply_url"] = actual_apply
                        results.append(item)
                    print(f"    [+] Saved {len(ld_items)} application/ld+json object(s)")
                else:
                    # Even if no ld+json found, record minimal structure
                    minimal_job = {
                        "_scraped_url": url,
                        "actual_apply_url": actual_apply
                    }
                    results.append(minimal_job)
                    print("    [-] No application/ld+json found, recorded basic metadata.")

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
        "--url",
        default=None,
        help="Open a specific URL for manual interaction without running the scraper"
    )
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
        "--extension", "-e",
        action="append",
        dest="extensions",
        help="Path to an unpacked Chrome extension folder (can be specified multiple times)"
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
    if args.positional_args and args.profile == "default":
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

    # Initialize scraper with chosen Persistent Profile, Browser, and Extensions
    scrapper = WebshareScrapper(
        headless=cli_args.headless,
        browser_type=cli_args.browser,
        profile=cli_args.profile,
        extensions=cli_args.extensions
    )

    # Mode 1: Open a single URL for manual interaction only
    if cli_args.url:
        target_url = cli_args.url.strip()
        if not target_url.startswith("http://") and not target_url.startswith("https://"):
            target_url = "https://" + target_url

        print(f"\n[*] Manual Interaction Mode")
        print(f"[*] Target URL: {target_url}")
        print(f"[*] Profile: {cli_args.profile} ({scrapper.user_data_dir})")

        try:
            await scrapper.start()

            if not cli_args.skip_ip_check:
                await scrapper.verify_proxy_ip()

            print(f"[*] Navigating to: {target_url}")
            await scrapper.page.goto(target_url, wait_until="domcontentloaded")
            print(f"[+] Loaded successfully: '{await scrapper.page.title()}'")
            print("[*] Browser is ready for manual interaction.")
            print("[*] When you are finished, close the browser window to save and exit.")
            await scrapper.wait_until_closed()

        except KeyboardInterrupt:
            print("\n[*] Script interrupted by user.")
        finally:
            await scrapper.close()
        return

    # Mode 2: Batch scraping job URLs from urls-file
    job_urls = load_job_urls(cli_args.urls_file)
    print(f"[*] Loaded {len(job_urls)} URL(s) from '{cli_args.urls_file}'.")
    
    try:
        await scrapper.start()
        
        # Check outbound IP
        if not cli_args.skip_ip_check:
            await scrapper.verify_proxy_ip()
        
        # Scrape application/ld+json and apply links for each job URL
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
