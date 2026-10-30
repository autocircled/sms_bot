# Webshare Playwright Job Schema Scraper

An anti-detect web scraper built with **Playwright**, designed to bypass bot detection (Cloudflare / Turnstile), route requests through **Webshare proxies**, and batch-extract Schema.org `application/ld+json` (`JobPosting`) data into structured JSON files.

---

## 🌟 Key Features

- **Anti-Bot & Stealth**:
  - Connects directly to your system's installed **Google Chrome** (`channel="chrome"`) or **Firefox** instead of standard automated Chromium builds.
  - Masks `navigator.webdriver` and injects realistic browser runtime properties (`window.chrome`, `navigator.plugins`, permissions queries).
  - Eliminates `--enable-automation` banners and unwanted warning flags.
- **Webshare Proxy Integration**:
  - Automatically loads proxies from `data/proxies.json` or falls back to Webshare credentials with randomized sub-user rotation.
- **Persistent Multi-Profile Management**:
  - Supports isolated profiles (`browser_profiles/<profile_name>`).
  - Sessions, cookies, logins, and CAPTCHA states persist across runs automatically.
- **Batch Job Scraping**:
  - Reads 50, 100, or more job URLs from a text file (`urls.txt`).
  - Extracts Schema.org `JobPosting` structured metadata.
  - Automatically saves progress incrementally to `scraped_jobs.json`.

---

## 📁 Project Structure

```text
sms_bot/
├── Scrapper.py          # Main scraper script
├── urls.txt             # List of target URLs to scrape (1 per line)
├── scraped_jobs.json    # Extracted job data output (JSON array)
├── requirements.txt     # Python dependencies
├── README.md            # Documentation
├── data/
│   ├── proxies.json     # Optional custom proxy configuration
│   └── codes.json       # Country codes cache (SMS service)
└── browser_profiles/   # Persistent browser profile storage (git-ignored)
    ├── default/
    ├── profile1/
    └── ...
```

---

## 🚀 Getting Started

### 1. Prerequisites & Environment Setup

Ensure your virtual environment is active and dependencies are installed:

```powershell
# Activate virtual environment
.\env\Scripts\Activate.ps1

# Install requirements
pip install -r requirements.txt

# (First-time only) Install Playwright browser drivers if needed
playwright install
```

---

## ⚙️ Configuration

### 1. Add Job URLs (`urls.txt`)
Paste the job URLs you want to scrape into `urls.txt`, one URL per line:

```text
https://www.dinjob.com/job/customer-service-associate-mv72gy9j-u582
https://www.dinjob.com/job/general-manager-mv71i1sm-5jru
https://www.dinjob.com/job/insurance-regulatory-and-compliance-associate-mv7115s4-0e4m
https://www.dinjob.com/job/retail-sales-supervisor-mv7026m6-beb9
```

### 2. Proxies (`data/proxies.json`)
The script automatically reads proxies formatted as `host:port:username:password`:

```json
{
    "proxies": [
        "p.webshare.io:80:username-1:password"
    ]
}
```
*If `data/proxies.json` is omitted, it falls back to the default Webshare backbone configured in `Scrapper.py`.*

---

## 📖 Usage & CLI Examples

### 1. Default Run (Chrome, Headful with GUI)
Opens Google Chrome, verifies proxy IP, visits each URL in `urls.txt`, and saves extracted data:
```powershell
.\env\Scripts\python.exe Scrapper.py
```
*(The browser will remain open after scraping until you manually close the window).*

---

### 2. Fast Background Scraping (Headless Mode)
Runs quietly in the background without opening a browser window:
```powershell
.\env\Scripts\python.exe Scrapper.py --headless
```

---

### 3. Using Multiple Isolated Profiles
Run different profiles to keep separate cookies, logins, or sessions:

```powershell
# Launch under a profile named 'account1'
.\env\Scripts\python.exe Scrapper.py --profile account1

# Launch under 'profile2'
.\env\Scripts\python.exe Scrapper.py --profile profile2
```
*Data for each profile is saved under `browser_profiles/<profile_name>/`.*

---

### 4. Switching Browser Engines
You can choose between system Chrome, Firefox, or Chromium:

```powershell
# Run with Firefox
.\env\Scripts\python.exe Scrapper.py --browser firefox

# Or shorthand
.\env\Scripts\python.exe Scrapper.py firefox profile2
```

---

### 5. Custom URLs File & Custom Output
Specify an alternative input file or output file path:

```powershell
.\env\Scripts\python.exe Scrapper.py --urls-file my_jobs.txt --output results.json --headless
```

---

### 6. Skip Proxy IP Verification
Skip the initial `ipv4.webshare.io` check to start scraping immediately:
```powershell
.\env\Scripts\python.exe Scrapper.py --skip-ip-check
```

---

### 7. Manual Interaction Mode (`--url`)
Open any website directly under a specific persistent profile without running the scraper. This allows you to manually log in, solve CAPTCHAs, or browse:

```powershell
.\env\Scripts\python.exe Scrapper.py --profile sandeep --url https://google.com
```
*(The browser will navigate to the site and remain open for your manual interaction until you close the browser window).*

---

### 8. Installing Extensions Manually (From Chrome Web Store)
You can install any extension directly from the Chrome Web Store and keep it forever in your profile:

1. Open your profile in manual interaction mode:
   ```powershell
   .\env\Scripts\python.exe Scrapper.py --profile sandeep --url https://chromewebstore.google.com
   ```
2. Search for any extension (e.g., uBlock Origin, CAPTCHA Solver, Cookie Editor) and click **"Add to Chrome"**.
3. Close the browser window when finished.

**That's it!** The extension and all of its settings, logins, and data are saved permanently inside `browser_profiles/<profile>/` and will remain active automatically every time you launch that profile.

---

### 9. Using Pre-Built Unpacked Extensions (`--extension`)
You can also load an unpacked local extension folder (containing `manifest.json`):

```powershell
# Load an unpacked extension into profile 'sandeep'
.\env\Scripts\python.exe Scrapper.py --profile sandeep --extension ./my_extension

# Combine with manual interaction
.\env\Scripts\python.exe Scrapper.py --profile sandeep --url https://google.com --extension ./my_extension

# Load multiple extensions
.\env\Scripts\python.exe Scrapper.py --profile sandeep -e ./extension1 -e ./extension2
```
*The extension's settings, logins, and storage are permanently preserved in that profile.*

---

## 🛠️ CLI Options Reference

| Flag / Option | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--url` | | `None` | Open a specific URL for manual interaction without scraping |
| `--extension` | `-e` | `None` | Path to unpacked Chrome extension folder (can repeat) |
| `--browser` | `-b` | `chrome` | Browser engine: `chrome`, `firefox`, or `chromium` |
| `--profile` | `-p` | `default` | Profile name or folder path inside `browser_profiles/` |
| `--headless` | | `False` | Run in headless background mode |
| `--urls-file`| `-u` | `urls.txt` | Text file containing job URLs to scrape |
| `--output` | `-o` | `scraped_jobs.json` | Path to the destination JSON file |
| `--skip-ip-check` | | `False` | Skip initial outbound IP check |

---

## 📊 Output Format (`scraped_jobs.json`)

The output is saved as a clean JSON array of Schema.org `JobPosting` objects:

```json
[
  {
    "@context": "https://schema.org/",
    "@type": "JobPosting",
    "title": "Customer Service Associate",
    "hiringOrganization": {
      "@type": "Organization",
      "name": "Hertz"
    },
    "jobLocation": {
      "@type": "Place",
      "address": {
        "@type": "PostalAddress",
        "addressLocality": "McAllen, TX, US"
      }
    },
    "baseSalary": {
      "@type": "MonetaryAmount",
      "currency": "USD",
      "value": {
        "@type": "QuantitativeValue",
        "minValue": 120000,
        "maxValue": 155000,
        "unitText": "YEAR"
      }
    },
    "datePosted": "2026-10-13T19:21:15.895Z",
    "description": "...",
    "_scraped_url": "https://www.dinjob.com/job/customer-service-associate-mv72gy9j-u582",
    "actual_apply_url": "https://grnh.se/e317mqkt9us"
  }
]
```
