from playwright.async_api import async_playwright
import requests
import asyncio
import random
import json
# import time
import sys
import os

API_KEY = 'd4ff8ce1-9792-4c91-ab69-fb1139b2c0f2'

async def what_is_my_ip(page):
    await page.goto("https://whatismyipaddress.com/")
    ip = page.get_by_text('IPv4:')
    country = page.locator('.ip-information .inner .information:nth-child(4)')
    print(await ip.text_content())
    print(await country.text_content())

async def check_current_ip(page):
    await page.goto("https://ipv4.webshare.io/")
    data = page.locator('body')
    print(await data.text_content())

def get_country_code(country_id):
    with open('data/codes.json', 'r') as f:
        data = json.load(f)
    
    countries = data['data']['countries']
    if countries:
        for country in countries:
            if country['id'] == country_id:
                return country['phone_code']
        return None
    else:
        return None

def get_number(country_id, operator_id = None):
    print(country_id, operator_id)
    country_code = get_country_code(country_id)

    if country_code:
        print("country Codes is :", country_code)
    else:
        print("Country code not found")
        return

    operator_param = f"&operator_id={operator_id}" if operator_id else ""

    req = requests.get(f'https://smsgen.net/api/get-number/{API_KEY}?country_id={country_id}{operator_param}').json()
    if req.get('status') == 'success' and 'data' in req:
        ph_number = req['data']['phone_number']
        print("Phone Number:", country_code, ph_number)
        return ph_number
    else:
        print("Error: Failed to get phone number")
        return None

async def automation_choise(page, phone_number):
    await page.goto("http://app.choise.com/sign-up")
    await page.locator('input[type=tel].TextField_text_input__vsxxp').fill(phone_number)
    await page.locator('input[type=password].TextField_text_input__vsxxp').fill('aasdskjsdkas4')
    await page.locator('img.sign__checkbox-check-img').click()
    await page.locator('button[type=submit]').click()


async def start_automation(proxies):
    if proxies:
        rand = random.choice(range(1, 100))
        proxy = {
            "server":'p.webshare.io:80',
            "username":f'9zngMBKFJQQ2Rg8V-{rand}',
            "password":'k6JurP73ejm23UwEK9SM4kH',
        }
        print(proxy)

    phone_number = get_number(181, 427)
    # print(phone_number)
    # return
    # phone_number = '8801774698525'
    async with async_playwright() as p:
        if proxies:
            browser = await p.firefox.launch(
                headless=False,
                slow_mo=5000,
                proxy=proxy
            )
        else:
            browser = await p.firefox.launch(
                headless=False,
                slow_mo=5000
            )

        context = await browser.new_context()
        page = await context.new_page()
        
        await automation_choise(page, phone_number)
        

        # check IP
        # await what_is_my_ip(page)
        # await check_current_ip(page)

        await context.close()
        await browser.close()
    

def fetch_updated_country_codes():
    req = requests.get(f'https://smsgen.net/api/init/{API_KEY}').json()
    
    os.makedirs('data', exist_ok=True)
    
    with open('data/codes.json', 'w') as f:
        json.dump(req, f, indent=4)

async def get_proxies():
    with open('data/proxies.json', 'r') as f:
        data = json.load(f)
    
    return data['proxies']

if __name__ == '__main__':    
    # print(sys.argv)
    fetch_updated_country_codes()

    proxies = asyncio.run(get_proxies()) if 'vpn' in sys.argv else None    
    while True:
        asyncio.run(start_automation(proxies))
        # time.sleep(2)

