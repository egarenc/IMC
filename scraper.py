import os
import json
import asyncio
from datetime import datetime
import pandas as pd
from playwright.async_api import async_playwright

INPUT_FILE = "input/asins.xlsx"
RESULTS_DIR = "results"
INDEX_FILE = os.path.join(RESULTS_DIR, "index.json")

async def scrape_buybox(page, asin):
    url = f"https://www.amazon.es/dp/{asin}"
    try:
        # User-Agent para minimizar bloqueos iniciales
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "es-ES,es;q=0.9"
        })
        
        response = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        
        if response.status != 200:
            return {"ASIN": asin, "Estado": f"Error HTTP {response.status}", "Precio": "", "Vendedor": "", "Disponibilidad": ""}

        # Selectores comunes de Buybox en Amazon
        price = await page.locator("#corePrice_feature_div .a-offscreen, #priceblock_ourprice, .a-price .a-offscreen").first.text_content(timeout=5000)
        seller = await page.locator("#merchant-info, #sellerProfileTriggerId").first.text_content(timeout=5000)
        availability = await page.locator("#availability").first.text_content(timeout=5000)

        return {
            "ASIN": asin,
            "Estado": "OK",
            "Precio": price.strip() if price else "N/D",
            "Vendedor": seller.strip() if seller else "N/D",
            "Disponibilidad": availability.strip() if availability else "N/D"
        }
    except Exception as e:
        return {"ASIN": asin, "Estado": f"Error: {str(e)}", "Precio": "", "Vendedor": "", "Disponibilidad": ""}

async def main():
    if not os.path.exists(INPUT_FILE):
        print("No se encontró el archivo de entrada.")
        return

    # Leer ASINs del Excel
    df_input = pd.read_excel(INPUT_FILE)
    asins = df_input['ASIN'].dropna().astype(str).tolist()

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        for asin in asins:
            data = await scrape_buybox(page, asin.strip())
            results.append(data)
            await asyncio.sleep(2) # Pausa preventiva entre peticiones

        await browser.close()

    # Guardar Excel de salida con Timestamp
    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    display_date = now.strftime("%Y-%m-%d %H:%M:%S")
    
    output_filename = f"resultado_{timestamp_str}.xlsx"
    output_path = os.path.join(RESULTS_DIR, output_filename)
    
    os.makedirs(RESULTS_DIR, exist_ok=True)
    pd.DataFrame(results).to_excel(output_path, index=False)

    # Actualizar el índice JSON con los últimos 10 archivos
    index_data = []
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r") as f:
                index_data = json.load(f)
        except Exception:
            index_data = []

    new_entry = {
        "name": output_filename,
        "date": display_date,
        "url": f"./results/{output_filename}"
    }

    # Insertar al inicio y mantener solo los últimos 10
    index_data.insert(0, new_entry)
    index_data = index_data[:10]

    with open(INDEX_FILE, "w") as f:
        json.dump(index_data, f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())