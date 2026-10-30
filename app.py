import asyncio
import json
import os
import sys
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional, List, Dict, Any

import customtkinter as ctk
import requests

from Scrapper import (
    WebshareScrapper,
    load_all_proxies_from_file,
    save_proxies_to_file,
    parse_proxy_string,
    resolve_profile_path,
    DEFAULT_PROXIES_FILE,
    DEFAULT_OUTPUT_FILE,
    DEFAULT_URLS_FILE
)

# Set UI Theme & Scaling
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class ScraperDesktopApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Playwright Webshare Scraper & Profile Hub")
        self.geometry("1100x750")
        self.minsize(950, 650)

        # State Variables
        self.is_scraping = False
        self.manual_browser_running = False
        self.scraper_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.active_manual_scrapper: Optional[WebshareScrapper] = None

        # Settings
        self.selected_browser = tk.StringVar(value="chrome")
        self.selected_profile = tk.StringVar(value="default")
        self.is_headless = tk.BooleanVar(value=False)
        self.skip_ip_check = tk.BooleanVar(value=False)
        self.min_delay_val = tk.DoubleVar(value=1.0)
        self.max_delay_val = tk.DoubleVar(value=2.5)
        self.output_file_path = tk.StringVar(value=DEFAULT_OUTPUT_FILE)
        self.custom_extension_path = tk.StringVar(value="")

        # Proxies In-Memory State
        self.proxies_list: List[str] = load_all_proxies_from_file()

        # Build Main Layout
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.create_sidebar()
        self.create_views()

        # Select Initial View
        self.select_view("scraper")
        self.refresh_profiles_list()

    # =========================================================================
    # SIDEBAR NAVIGATION
    # =========================================================================
    def create_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, width=210, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(6, weight=1)

        # App Brand Title
        self.logo_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="⚡ Scraper Hub",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(25, 20))

        # Nav Buttons
        self.btn_nav_scraper = ctk.CTkButton(
            self.sidebar_frame,
            text="🚀 Job Scraper",
            anchor="w",
            font=ctk.CTkFont(size=14),
            command=lambda: self.select_view("scraper")
        )
        self.btn_nav_scraper.grid(row=1, column=0, padx=15, pady=6, sticky="ew")

        self.btn_nav_browser = ctk.CTkButton(
            self.sidebar_frame,
            text="🌐 Manual Browser",
            anchor="w",
            font=ctk.CTkFont(size=14),
            command=lambda: self.select_view("browser")
        )
        self.btn_nav_browser.grid(row=2, column=0, padx=15, pady=6, sticky="ew")

        self.btn_nav_proxies = ctk.CTkButton(
            self.sidebar_frame,
            text="🛡️ Proxy Manager",
            anchor="w",
            font=ctk.CTkFont(size=14),
            command=lambda: self.select_view("proxies")
        )
        self.btn_nav_proxies.grid(row=3, column=0, padx=15, pady=6, sticky="ew")

        self.btn_nav_settings = ctk.CTkButton(
            self.sidebar_frame,
            text="⚙️ Settings",
            anchor="w",
            font=ctk.CTkFont(size=14),
            command=lambda: self.select_view("settings")
        )
        self.btn_nav_settings.grid(row=4, column=0, padx=15, pady=6, sticky="ew")

        # Sidebar Footer Profile Selector
        self.sidebar_profile_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="Active Profile:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.sidebar_profile_label.grid(row=7, column=0, padx=15, pady=(10, 2), sticky="w")

        self.profile_dropdown = ctk.CTkOptionMenu(
            self.sidebar_frame,
            variable=self.selected_profile,
            values=["default"],
            command=self.on_profile_changed
        )
        self.profile_dropdown.grid(row=8, column=0, padx=15, pady=(0, 20), sticky="ew")

    def select_view(self, name: str):
        # Update Nav Highlight
        buttons = {
            "scraper": self.btn_nav_scraper,
            "browser": self.btn_nav_browser,
            "proxies": self.btn_nav_proxies,
            "settings": self.btn_nav_settings,
        }
        for v_name, btn in buttons.items():
            if v_name == name:
                btn.configure(fg_color=["#3B8ED0", "#1F6AA5"])
            else:
                btn.configure(fg_color="transparent")

        # Hide all frames
        for frame in [self.view_scraper, self.view_browser, self.view_proxies, self.view_settings]:
            frame.grid_forget()

        # Show target frame
        if name == "scraper":
            self.view_scraper.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        elif name == "browser":
            self.view_browser.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        elif name == "proxies":
            self.view_proxies.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
            self.render_proxy_list()
        elif name == "settings":
            self.view_settings.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)

    # =========================================================================
    # CREATE ALL VIEW PANELS
    # =========================================================================
    def create_views(self):
        self.create_scraper_view()
        self.create_browser_view()
        self.create_proxies_view()
        self.create_settings_view()

    # -------------------------------------------------------------------------
    # VIEW 1: JOB SCRAPER & BATCH URLS
    # -------------------------------------------------------------------------
    def create_scraper_view(self):
        self.view_scraper = ctk.CTkFrame(self, corner_radius=10)
        self.view_scraper.grid_columnconfigure(0, weight=1)
        self.view_scraper.grid_rowconfigure(2, weight=1)

        # Header Row
        header_frame = ctk.CTkFrame(self.view_scraper, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 10))
        header_frame.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header_frame,
            text="Batch Job Schema Scraper",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        title.grid(row=0, column=0, sticky="w")

        self.scraper_status_badge = ctk.CTkLabel(
            header_frame,
            text="Ready",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2E7D32",
            corner_radius=6,
            padx=12,
            pady=4
        )
        self.scraper_status_badge.grid(row=0, column=1, sticky="e")

        # Top Control & URL Input Area
        top_ctrl = ctk.CTkFrame(self.view_scraper)
        top_ctrl.grid(row=1, column=0, sticky="ew", padx=15, pady=5)
        top_ctrl.grid_columnconfigure(0, weight=1)

        url_label = ctk.CTkLabel(
            top_ctrl,
            text="Paste Target Job URLs (one per line):",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        url_label.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))

        btn_row = ctk.CTkFrame(top_ctrl, fg_color="transparent")
        btn_row.grid(row=0, column=1, sticky="e", padx=10, pady=(10, 2))

        btn_load = ctk.CTkButton(btn_row, text="📂 Load File", width=90, height=28, command=self.load_urls_from_file_dialog)
        btn_load.pack(side="left", padx=4)

        btn_paste = ctk.CTkButton(btn_row, text="📋 Paste", width=80, height=28, command=self.paste_urls_from_clipboard)
        btn_paste.pack(side="left", padx=4)

        btn_clear = ctk.CTkButton(btn_row, text="🗑️ Clear", width=70, height=28, fg_color="#C62828", hover_color="#8E0000", command=self.clear_urls_text)
        btn_clear.pack(side="left", padx=4)

        # Multi-line URLs Textbox
        self.urls_text = ctk.CTkTextbox(top_ctrl, height=130, font=ctk.CTkFont(size=12))
        self.urls_text.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=8)

        # Pre-fill with sample URLs if urls.txt exists
        sample_urls = self.read_default_urls()
        if sample_urls:
            self.urls_text.insert("1.0", "\n".join(sample_urls))

        # Action Buttons Row
        act_row = ctk.CTkFrame(top_ctrl, fg_color="transparent")
        act_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 12))

        self.btn_start_scrap = ctk.CTkButton(
            act_row,
            text="▶ Start Scraping",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            height=36,
            command=self.start_scraping_job
        )
        self.btn_start_scrap.pack(side="left", padx=(0, 10))

        self.btn_stop_scrap = ctk.CTkButton(
            act_row,
            text="⏹ Stop",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#C62828",
            hover_color="#8E0000",
            height=36,
            state="disabled",
            command=self.stop_scraping_job
        )
        self.btn_stop_scrap.pack(side="left", padx=(0, 15))

        self.progress_bar = ctk.CTkProgressBar(act_row)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=10)
        self.progress_bar.set(0.0)

        self.progress_label = ctk.CTkLabel(act_row, text="0 / 0", font=ctk.CTkFont(size=12, weight="bold"))
        self.progress_label.pack(side="left", padx=5)

        # Live Console Output Box
        console_frame = ctk.CTkFrame(self.view_scraper)
        console_frame.grid(row=2, column=0, sticky="nsew", padx=15, pady=(5, 10))
        console_frame.grid_columnconfigure(0, weight=1)
        console_frame.grid_rowconfigure(1, weight=1)

        c_header = ctk.CTkFrame(console_frame, fg_color="transparent")
        c_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        c_header.grid_columnconfigure(0, weight=1)

        log_title = ctk.CTkLabel(c_header, text="Live Log Terminal", font=ctk.CTkFont(size=12, weight="bold"))
        log_title.grid(row=0, column=0, sticky="w")

        btn_clear_log = ctk.CTkButton(c_header, text="Clear Log", width=70, height=22, font=ctk.CTkFont(size=11), command=self.clear_log)
        btn_clear_log.grid(row=0, column=1, sticky="e")

        self.console_text = ctk.CTkTextbox(
            console_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#1E1E1E",
            text_color="#ECEFF1"
        )
        self.console_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(2, 10))

        # Bottom Bar for Results
        bottom_bar = ctk.CTkFrame(self.view_scraper, fg_color="transparent")
        bottom_bar.grid(row=3, column=0, sticky="ew", padx=15, pady=(0, 15))

        self.result_status_label = ctk.CTkLabel(
            bottom_bar,
            text=f"Destination: {os.path.abspath(DEFAULT_OUTPUT_FILE)}",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.result_status_label.pack(side="left")

        btn_open_json = ctk.CTkButton(
            bottom_bar,
            text="📄 View Output JSON",
            width=140,
            height=28,
            command=self.open_output_file
        )
        btn_open_json.pack(side="right", padx=(8, 0))

    # -------------------------------------------------------------------------
    # VIEW 2: MANUAL BROWSER & PROFILE MANAGER
    # -------------------------------------------------------------------------
    def create_browser_view(self):
        self.view_browser = ctk.CTkFrame(self, corner_radius=10)
        self.view_browser.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(
            self.view_browser,
            text="Manual Browser & Profile Controller",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        header.grid(row=0, column=0, sticky="w", padx=20, pady=(20, 10))

        desc = ctk.CTkLabel(
            self.view_browser,
            text="Launch any persistent profile to manually log in, solve Cloudflare CAPTCHAs, or install extensions.\nAll sessions, cookies, and installed extensions are saved permanently.",
            justify="left",
            text_color="gray"
        )
        desc.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 15))

        # Profile Controls
        prof_card = ctk.CTkFrame(self.view_browser)
        prof_card.grid(row=2, column=0, sticky="ew", padx=20, pady=10)
        prof_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(prof_card, text="Target Profile:", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, padx=15, pady=15, sticky="w")
        self.browser_prof_dropdown = ctk.CTkOptionMenu(
            prof_card,
            variable=self.selected_profile,
            values=["default"],
            command=self.on_profile_changed
        )
        self.browser_prof_dropdown.grid(row=0, column=1, padx=10, pady=15, sticky="w")

        btn_new_prof = ctk.CTkButton(prof_card, text="+ New Profile", width=110, command=self.prompt_create_profile)
        btn_new_prof.grid(row=0, column=2, padx=5, pady=15)

        btn_open_dir = ctk.CTkButton(prof_card, text="📁 Open Folder", width=110, fg_color="#37474F", command=self.open_profile_folder)
        btn_open_dir.grid(row=0, column=3, padx=(5, 15), pady=15)

        # URL Input Row
        url_card = ctk.CTkFrame(self.view_browser)
        url_card.grid(row=3, column=0, sticky="ew", padx=20, pady=10)
        url_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(url_card, text="Target URL:", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, padx=15, pady=12, sticky="w")
        self.manual_url_entry = ctk.CTkEntry(url_card, placeholder_text="https://example.com or https://chromewebstore.google.com")
        self.manual_url_entry.grid(row=0, column=1, padx=10, pady=12, sticky="ew")
        self.manual_url_entry.insert(0, "https://google.com")

        # Preset Quick Buttons
        preset_frame = ctk.CTkFrame(url_card, fg_color="transparent")
        preset_frame.grid(row=1, column=1, sticky="w", padx=10, pady=(0, 12))

        presets = [
            ("Google", "https://google.com"),
            ("Chrome Web Store", "https://chromewebstore.google.com"),
            ("Check IP", "https://ipv4.webshare.io/"),
            ("DinJob", "https://www.dinjob.com/"),
        ]
        for label, url in presets:
            btn = ctk.CTkButton(
                preset_frame,
                text=label,
                width=80,
                height=24,
                font=ctk.CTkFont(size=11),
                fg_color="#455A64",
                command=lambda u=url: self.set_manual_url(u)
            )
            btn.pack(side="left", padx=3)

        # Extension Folder Option
        ext_card = ctk.CTkFrame(self.view_browser)
        ext_card.grid(row=4, column=0, sticky="ew", padx=20, pady=10)
        ext_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(ext_card, text="Unpacked Extension (Optional):", font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, padx=15, pady=12, sticky="w")
        self.ext_entry = ctk.CTkEntry(ext_card, textvariable=self.custom_extension_path, placeholder_text="Select folder with manifest.json")
        self.ext_entry.grid(row=0, column=1, padx=10, pady=12, sticky="ew")

        btn_browse_ext = ctk.CTkButton(ext_card, text="Browse...", width=90, command=self.browse_extension_folder)
        btn_browse_ext.grid(row=0, column=2, padx=15, pady=12)

        # Launch Button
        launch_frame = ctk.CTkFrame(self.view_browser, fg_color="transparent")
        launch_frame.grid(row=5, column=0, sticky="ew", padx=20, pady=25)

        self.btn_launch_manual = ctk.CTkButton(
            launch_frame,
            text="🚀 Launch Browser Window",
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#1E88E5",
            hover_color="#1565C0",
            height=44,
            command=self.launch_manual_browser
        )
        self.btn_launch_manual.pack(side="left", padx=(0, 15))

        self.manual_status_label = ctk.CTkLabel(
            launch_frame,
            text="Status: Browser is not running.",
            font=ctk.CTkFont(size=13),
            text_color="gray"
        )
        self.manual_status_label.pack(side="left")

    # -------------------------------------------------------------------------
    # VIEW 3: PROXY MANAGER
    # -------------------------------------------------------------------------
    def create_proxies_view(self):
        self.view_proxies = ctk.CTkFrame(self, corner_radius=10)
        self.view_proxies.grid_columnconfigure(0, weight=1)
        self.view_proxies.grid_rowconfigure(2, weight=1)

        # Header
        p_header = ctk.CTkFrame(self.view_proxies, fg_color="transparent")
        p_header.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        p_header.grid_columnconfigure(0, weight=1)

        p_title = ctk.CTkLabel(
            p_header,
            text="Webshare Proxy Manager",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        p_title.grid(row=0, column=0, sticky="w")

        self.proxy_count_label = ctk.CTkLabel(
            p_header,
            text=f"Total: {len(self.proxies_list)} proxies",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#37474F",
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.proxy_count_label.grid(row=0, column=1, sticky="e")

        # Add Proxy Section
        add_frame = ctk.CTkFrame(self.view_proxies)
        add_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=5)
        add_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            add_frame,
            text="Add New Proxy (Format: host:port:username:password):",
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(10, 2))

        input_row = ctk.CTkFrame(add_frame, fg_color="transparent")
        input_row.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 12))
        input_row.grid_columnconfigure(0, weight=1)

        self.proxy_input_entry = ctk.CTkEntry(
            input_row,
            placeholder_text="p.webshare.io:80:user-1:password"
        )
        self.proxy_input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        btn_add = ctk.CTkButton(input_row, text="➕ Add Proxy", width=110, command=self.add_single_proxy)
        btn_add.grid(row=0, column=1, padx=(0, 8))

        btn_bulk = ctk.CTkButton(input_row, text="📋 Bulk Import", width=110, fg_color="#455A64", command=self.prompt_bulk_proxies)
        btn_bulk.grid(row=0, column=2)

        # Scrollable Proxy List
        self.proxy_scroll_frame = ctk.CTkScrollableFrame(self.view_proxies, label_text="Configured Proxies (data/proxies.json)")
        self.proxy_scroll_frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=10)
        self.proxy_scroll_frame.grid_columnconfigure(0, weight=1)

        # Bottom Bar for Global Actions
        p_bottom = ctk.CTkFrame(self.view_proxies, fg_color="transparent")
        p_bottom.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 15))

        btn_test_all = ctk.CTkButton(p_bottom, text="🧪 Test First Working Proxy", fg_color="#1E88E5", command=self.test_active_proxy)
        btn_test_all.pack(side="left")

        self.proxy_test_status = ctk.CTkLabel(p_bottom, text="", font=ctk.CTkFont(size=12, weight="bold"))
        self.proxy_test_status.pack(side="left", padx=15)

    # -------------------------------------------------------------------------
    # VIEW 4: SETTINGS & CONFIGURATION
    # -------------------------------------------------------------------------
    def create_settings_view(self):
        self.view_settings = ctk.CTkFrame(self, corner_radius=10)
        self.view_settings.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(
            self.view_settings,
            text="Application Settings",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        header.grid(row=0, column=0, sticky="w", padx=20, pady=(20, 15))

        # Browser Engine Section
        engine_card = ctk.CTkFrame(self.view_settings)
        engine_card.grid(row=1, column=0, sticky="ew", padx=20, pady=10)
        engine_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(engine_card, text="Browser Engine:", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, padx=15, pady=15, sticky="w")
        self.engine_selector = ctk.CTkSegmentedButton(
            engine_card,
            values=["chrome", "firefox", "chromium"],
            variable=self.selected_browser
        )
        self.engine_selector.grid(row=0, column=1, padx=15, pady=15, sticky="w")

        # Headless & IP Check Toggles
        opt_card = ctk.CTkFrame(self.view_settings)
        opt_card.grid(row=2, column=0, sticky="ew", padx=20, pady=10)

        ctk.CTkSwitch(
            opt_card,
            text="Run in Headless Mode (Quiet background scraping)",
            variable=self.is_headless,
            font=ctk.CTkFont(size=13)
        ).grid(row=0, column=0, padx=15, pady=12, sticky="w")

        ctk.CTkSwitch(
            opt_card,
            text="Skip Outbound IP Verification on startup (Faster start)",
            variable=self.skip_ip_check,
            font=ctk.CTkFont(size=13)
        ).grid(row=1, column=0, padx=15, pady=(0, 12), sticky="w")

        # Delays
        delay_card = ctk.CTkFrame(self.view_settings)
        delay_card.grid(row=3, column=0, sticky="ew", padx=20, pady=10)
        delay_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(delay_card, text="Random Inter-Page Request Delay (seconds):", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, columnspan=2, padx=15, pady=(12, 5), sticky="w")

        d_row = ctk.CTkFrame(delay_card, fg_color="transparent")
        d_row.grid(row=1, column=0, columnspan=2, sticky="w", padx=15, pady=(0, 15))

        ctk.CTkLabel(d_row, text="Min Delay:").pack(side="left", padx=(0, 5))
        d_min = ctk.CTkEntry(d_row, width=60, textvariable=self.min_delay_val)
        d_min.pack(side="left", padx=(0, 20))

        ctk.CTkLabel(d_row, text="Max Delay:").pack(side="left", padx=(0, 5))
        d_max = ctk.CTkEntry(d_row, width=60, textvariable=self.max_delay_val)
        d_max.pack(side="left")

        # Output File Path
        out_card = ctk.CTkFrame(self.view_settings)
        out_card.grid(row=4, column=0, sticky="ew", padx=20, pady=10)
        out_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(out_card, text="Output JSON File:", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, padx=15, pady=15, sticky="w")
        self.out_entry = ctk.CTkEntry(out_card, textvariable=self.output_file_path)
        self.out_entry.grid(row=0, column=1, padx=10, pady=15, sticky="ew")

        btn_browse_out = ctk.CTkButton(out_card, text="Browse...", width=90, command=self.browse_output_file)
        btn_browse_out.grid(row=0, column=2, padx=15, pady=15)

    # =========================================================================
    # SCRAPER WORKER LOGIC (NON-BLOCKING THREAD)
    # =========================================================================
    def start_scraping_job(self):
        raw_text = self.urls_text.get("1.0", "end").strip()
        urls = [line.strip() for line in raw_text.splitlines() if line.strip() and not line.strip().startswith("#")]

        if not urls:
            messagebox.showwarning("No URLs", "Please enter at least one job URL in the text box.")
            return

        self.is_scraping = True
        self.stop_event.clear()

        # Update UI Controls
        self.btn_start_scrap.configure(state="disabled")
        self.btn_stop_scrap.configure(state="normal")
        self.scraper_status_badge.configure(text="Scraping...", fg_color="#F57C00")
        self.progress_bar.set(0.0)
        self.progress_label.configure(text=f"0 / {len(urls)}")

        # Collect Configuration
        browser_type = self.selected_browser.get()
        profile = self.selected_profile.get()
        headless = self.is_headless.get()
        skip_ip = self.skip_ip_check.get()
        output_file = self.output_file_path.get().strip() or DEFAULT_OUTPUT_FILE
        delays = (self.min_delay_val.get(), self.max_delay_val.get())
        ext_list = [self.custom_extension_path.get().strip()] if self.custom_extension_path.get().strip() else []

        self.log(f"[*] Starting Batch Scraping for {len(urls)} URL(s)...")
        self.log(f"[*] Browser: {browser_type.upper()} | Profile: {profile} | Headless: {headless}")

        # Launch in background thread
        self.scraper_thread = threading.Thread(
            target=self._run_scraper_async_thread,
            args=(urls, browser_type, profile, headless, skip_ip, output_file, delays, ext_list),
            daemon=True
        )
        self.scraper_thread.start()

    def _run_scraper_async_thread(self, urls, browser_type, profile, headless, skip_ip, output_file, delays, ext_list):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        scrapper = WebshareScrapper(
            headless=headless,
            browser_type=browser_type,
            profile=profile,
            extensions=ext_list
        )

        try:
            loop.run_until_complete(scrapper.start())

            if not skip_ip:
                loop.run_until_complete(scrapper.verify_proxy_ip(on_log=self.log))

            # Run Batch with thread callbacks
            loop.run_until_complete(
                scrapper.scrape_jobs_batch(
                    urls=urls,
                    output_file=output_file,
                    delay_range=delays,
                    on_log=self.log,
                    on_progress=self.on_scrape_progress,
                    stop_event=self.stop_event
                )
            )

        except Exception as e:
            self.log(f"[!] Scraper Error: {e}")
        finally:
            try:
                loop.run_until_complete(scrapper.close())
            except Exception:
                pass
            loop.close()

            # Reset UI on completion
            self.after(0, self._on_scraping_finished)

    def stop_scraping_job(self):
        if self.is_scraping:
            self.stop_event.set()
            self.log("[*] Stopping scraper... waiting for active page to finish.")
            self.btn_stop_scrap.configure(state="disabled")

    def _on_scraping_finished(self):
        self.is_scraping = False
        self.btn_start_scrap.configure(state="normal")
        self.btn_stop_scrap.configure(state="disabled")
        self.scraper_status_badge.configure(text="Finished", fg_color="#2E7D32")
        self.log("[✓] Scraping process terminated.")

    def on_scrape_progress(self, index: int, total: int, current_job: Optional[Dict[str, Any]]):
        def _update():
            fraction = index / total if total > 0 else 0.0
            self.progress_bar.set(fraction)
            self.progress_label.configure(text=f"{index} / {total}")
        self.after(0, _update)

    # =========================================================================
    # MANUAL BROWSER RUNNER (NON-BLOCKING THREAD)
    # =========================================================================
    def launch_manual_browser(self):
        if self.manual_browser_running:
            messagebox.showinfo("Browser Running", "A manual browser instance is already running.")
            return

        target_url = self.manual_url_entry.get().strip() or "https://google.com"
        if not target_url.startswith("http://") and not target_url.startswith("https://"):
            target_url = "https://" + target_url

        profile = self.selected_profile.get()
        browser_type = self.selected_browser.get()
        ext_list = [self.custom_extension_path.get().strip()] if self.custom_extension_path.get().strip() else []

        self.manual_browser_running = True
        self.btn_launch_manual.configure(state="disabled")
        self.manual_status_label.configure(text=f"Status: Browser OPEN with profile '{profile}'. Close window to exit.", text_color="#64B5F6")

        threading.Thread(
            target=self._run_manual_browser_thread,
            args=(target_url, browser_type, profile, ext_list),
            daemon=True
        )

    def _run_manual_browser_thread(self, target_url, browser_type, profile, ext_list):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        scrapper = WebshareScrapper(
            headless=False,
            browser_type=browser_type,
            profile=profile,
            extensions=ext_list
        )

        try:
            loop.run_until_complete(scrapper.start())
            if not self.skip_ip_check.get():
                loop.run_until_complete(scrapper.verify_proxy_ip())

            loop.run_until_complete(scrapper.page.goto(target_url, wait_until="domcontentloaded"))
            loop.run_until_complete(scrapper.wait_until_closed())

        except Exception as e:
            print(f"[!] Manual Browser Error: {e}")
        finally:
            try:
                loop.run_until_complete(scrapper.close())
            except Exception:
                pass
            loop.close()

            def _reset():
                self.manual_browser_running = False
                self.btn_launch_manual.configure(state="normal")
                self.manual_status_label.configure(text="Status: Browser closed. Session saved.", text_color="gray")
            self.after(0, _reset)

    # =========================================================================
    # PROXY MANAGEMENT
    # =========================================================================
    def render_proxy_list(self):
        # Clear existing rows
        for widget in self.proxy_scroll_frame.winfo_children():
            widget.destroy()

        self.proxy_count_label.configure(text=f"Total: {len(self.proxies_list)} proxies")

        if not self.proxies_list:
            empty_lbl = ctk.CTkLabel(
                self.proxy_scroll_frame,
                text="No proxies configured in data/proxies.json.\nClick 'Add Proxy' or 'Bulk Import' above.",
                text_color="gray",
                pady=30
            )
            empty_lbl.pack()
            return

        for idx, p_str in enumerate(self.proxies_list):
            row_frame = ctk.CTkFrame(self.proxy_scroll_frame)
            row_frame.pack(fill="x", padx=5, pady=4)
            row_frame.grid_columnconfigure(0, weight=1)

            # Mask Password for clean display
            parts = p_str.split(":")
            if len(parts) == 4:
                display_str = f"🌐 {parts[0]}:{parts[1]}   👤 {parts[2]}   🔑 {'•' * 8}"
            else:
                display_str = f"🌐 {p_str}"

            lbl = ctk.CTkLabel(row_frame, text=display_str, anchor="w", font=ctk.CTkFont(family="Consolas", size=12))
            lbl.grid(row=0, column=0, padx=12, pady=8, sticky="w")

            btn_del = ctk.CTkButton(
                row_frame,
                text="❌",
                width=32,
                height=28,
                fg_color="#C62828",
                hover_color="#8E0000",
                command=lambda i=idx: self.delete_proxy(i)
            )
            btn_del.grid(row=0, column=1, padx=(0, 10), pady=8)

    def add_single_proxy(self):
        val = self.proxy_input_entry.get().strip()
        if not val:
            return
        try:
            parse_proxy_string(val)
        except Exception as e:
            messagebox.showerror("Invalid Format", f"Proxy must be in 'host:port:user:pass' format.\nError: {e}")
            return

        self.proxies_list.append(val)
        save_proxies_to_file(self.proxies_list)
        self.proxy_input_entry.delete(0, "end")
        self.render_proxy_list()

    def delete_proxy(self, index: int):
        if 0 <= index < len(self.proxies_list):
            self.proxies_list.pop(index)
            save_proxies_to_file(self.proxies_list)
            self.render_proxy_list()

    def prompt_bulk_proxies(self):
        dialog = ctk.CTkInputDialog(
            text="Paste proxies (one per line, host:port:user:pass):",
            title="Bulk Import Proxies"
        )
        val = dialog.get_input()
        if val:
            added = 0
            for line in val.splitlines():
                cleaned = line.strip()
                if cleaned:
                    try:
                        parse_proxy_string(cleaned)
                        self.proxies_list.append(cleaned)
                        added += 1
                    except Exception:
                        pass
            if added > 0:
                save_proxies_to_file(self.proxies_list)
                self.render_proxy_list()
                messagebox.showinfo("Success", f"Added {added} valid proxy entries.")

    def test_active_proxy(self):
        if not self.proxies_list:
            messagebox.showinfo("No Proxies", "Please add at least one proxy first.")
            return

        self.proxy_test_status.configure(text="Testing connection...", text_color="#FFB300")

        def _test():
            target_proxy = self.proxies_list[0]
            try:
                conf = parse_proxy_string(target_proxy)
                proxy_url = f"http://{conf['username']}:{conf['password']}@{conf['server'].replace('http://', '')}"
                res = requests.get("https://ipv4.webshare.io/", proxies={"http": proxy_url, "https": proxy_url}, timeout=10)
                ip = res.text.strip()
                self.after(0, lambda: self.proxy_test_status.configure(text=f"✔ Connected! Outbound IP: {ip}", text_color="#4CAF50"))
            except Exception as e:
                self.after(0, lambda: self.proxy_test_status.configure(text=f"✖ Test failed: {e}", text_color="#EF5350"))

        threading.Thread(target=_test, daemon=True).start()

    # =========================================================================
    # PROFILE UTILITIES
    # =========================================================================
    def refresh_profiles_list(self):
        profiles = ["default"]
        profiles_dir = "browser_profiles"
        if os.path.exists(profiles_dir):
            for item in os.listdir(profiles_dir):
                full = os.path.join(profiles_dir, item)
                if os.path.isdir(full) and item not in profiles:
                    profiles.append(item)

        self.profile_dropdown.configure(values=profiles)
        self.browser_prof_dropdown.configure(values=profiles)

    def on_profile_changed(self, choice: str):
        self.selected_profile.set(choice)

    def prompt_create_profile(self):
        dialog = ctk.CTkInputDialog(text="Enter new profile name (e.g. 'account2', 'sandeep'):", title="New Profile")
        name = dialog.get_input()
        if name:
            clean = name.strip().replace(" ", "_")
            path = resolve_profile_path(clean)
            os.makedirs(path, exist_ok=True)
            self.refresh_profiles_list()
            self.selected_profile.set(clean)
            messagebox.showinfo("Profile Created", f"Profile '{clean}' created at: {path}")

    def open_profile_folder(self):
        path = os.path.abspath(resolve_profile_path(self.selected_profile.get()))
        os.makedirs(path, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", path])

    # =========================================================================
    # UI HELPER ACTIONS
    # =========================================================================
    def log(self, text: str):
        def _write():
            self.console_text.insert("end", text + "\n")
            self.console_text.see("end")
        self.after(0, _write)

    def clear_log(self):
        self.console_text.delete("1.0", "end")

    def clear_urls_text(self):
        self.urls_text.delete("1.0", "end")

    def paste_urls_from_clipboard(self):
        try:
            clip = self.clipboard_get()
            if clip:
                self.urls_text.insert("end", ("\n" if self.urls_text.get("1.0", "end").strip() else "") + clip.strip())
        except Exception:
            pass

    def load_urls_from_file_dialog(self):
        filepath = filedialog.askopenfilename(
            title="Select URLs File",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if filepath and os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            self.urls_text.delete("1.0", "end")
            self.urls_text.insert("1.0", content)

    def read_default_urls(self) -> List[str]:
        if os.path.exists(DEFAULT_URLS_FILE):
            with open(DEFAULT_URLS_FILE, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
        return []

    def set_manual_url(self, url: str):
        self.manual_url_entry.delete(0, "end")
        self.manual_url_entry.insert(0, url)

    def browse_extension_folder(self):
        folder = filedialog.askdirectory(title="Select Unpacked Extension Directory")
        if folder:
            self.custom_extension_path.set(folder)

    def browse_output_file(self):
        f = filedialog.asksaveasfilename(
            title="Select Output JSON Path",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")]
        )
        if f:
            self.output_file_path.set(f)
            self.result_status_label.configure(text=f"Destination: {os.path.abspath(f)}")

    def open_output_file(self):
        path = os.path.abspath(self.output_file_path.get())
        if os.path.exists(path):
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", path])
        else:
            messagebox.showinfo("Not Found", f"Output file does not exist yet:\n{path}")


if __name__ == "__main__":
    app = ScraperDesktopApp()
    app.mainloop()
