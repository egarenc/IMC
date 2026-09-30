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
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "es-ES,es;q=0.9"
        })
        
        response = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        
        if response.status != 200:
            return {"ASIN": asin, "Estado": f"Error HTTP {response.status}", "Precio": "N/D", "Vendedor": "N/D", "Disponibilidad": "N/D"}

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
        return {"ASIN": asin, "Estado": f"Error: {str(e)}", "Precio": "N/D", "Vendedor": "N/D", "Disponibilidad": "N/D"}

async def main():
    print("--- INICIANDO PROCESO DE SCRAPING ---")
    print(f"Directorio actual: {os.getcwd()}")
    
    if not os.path.exists(INPUT_FILE):
        raise FileNotFoundError(f"❌ ERROR CRÍTICO: No existe el archivo {INPUT_FILE}")

    # Leer Excel
    df_input = pd.read_excel(INPUT_FILE)
    print(f"Cabeceras detectadas en el Excel: {list(df_input.columns)}")

    # Buscar columna ASIN (tolerante a mayúsculas/minúsculas/espacios)
    col_asin = [c for c in df_input.columns if str(c).strip().upper() == 'ASIN']
    if not col_asin:
        raise ValueError(f"❌ ERROR: No se encontró la columna 'ASIN'. Cabeceras presentes: {list(df_input.columns)}")

    asins = df_input[col_asin[0]].dropna().astype(str).str.strip().tolist()
    print(f"✅ ASINs cargados para procesar ({len(asins)}): {asins}")

    if not asins:
        raise ValueError("❌ ERROR: La columna ASIN existe pero no contiene ningún dato.")

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        for asin in asins:
            print(f"Procesando ASIN: {asin}...")
            data = await scrape_buybox(page, asin)
            print(f" -> Resultado: {data['Estado']} | Precio: {data['Precio']}")
            results.append(data)
            await asyncio.sleep(2)

        await browser.close()

    # Guardar Excel de salida con Timestamp
    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    display_date = now.strftime("%Y-%m-%d %H:%M:%S")
    
    output_filename = f"resultado_{timestamp_str}.xlsx"
    output_path = os.path.join(RESULTS_DIR, output_filename)
    
    os.makedirs(RESULTS_DIR, exist_ok=True)
    pd.DataFrame(results).to_excel(output_path, index=False)
    print(f"✅ Excel de resultados creado correctamente en: {output_path}")

    # Actualizar index.json
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

    index_data.insert(0, new_entry)
    index_data = index_data[:10]

    with open(INDEX_FILE, "w") as f:
        json.dump(index_data, f, indent=2)
    print(f"✅ Archivo {INDEX_FILE} actualizado con éxito.")

if __name__ == "__main__":
    asyncio.run(main())
