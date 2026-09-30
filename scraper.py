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
        response = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(2) # Pausa para renderizado JS

        # 1. Comprobar si Amazon devolvió un CAPTCHA
        title = await page.title()
        content = await page.content()
        
        if "captcha" in title.lower() or "robot" in title.lower() or "validateCaptcha" in content or "algo ha ido mal" in content.lower():
            print(f"⚠️ CAPTCHA/Bloqueo detectado para ASIN: {asin}")
            return {
                "ASIN": asin,
                "Estado": "Bloqueado (CAPTCHA de Amazon)",
                "Precio": "N/D",
                "Vendedor": "N/D",
                "Disponibilidad": "N/D"
            }

        if response and response.status != 200:
            return {
                "ASIN": asin,
                "Estado": f"Error HTTP {response.status}",
                "Precio": "N/D",
                "Vendedor": "N/D",
                "Disponibilidad": "N/D"
            }

        price_val = "N/D"
        seller_val = "N/D"
        avail_val = "N/D"

        # 2. Extracción de Precio con selectores alternativos
        try:
            price_selectors = [
                "#corePrice_feature_div .a-offscreen",
                "#corePriceDisplay_desktop_feature_div .a-offscreen",
                "#priceblock_ourprice",
                ".a-price .a-offscreen",
                "#price_inside_buybox"
            ]
            for sel in price_selectors:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    txt = await loc.text_content(timeout=2000)
                    if txt and txt.strip():
                        price_val = txt.strip()
                        break
        except Exception:
            pass

        # 3. Extracción de Vendedor con selectores alternativos
        try:
            seller_selectors = [
                "#merchant-info",
                "#sellerProfileTriggerId",
                "#tabular-buybox .tabular-buybox-text[s-seller]",
                "#fbaProfileTriggerId"
            ]
            for sel in seller_selectors:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    txt = await loc.text_content(timeout=2000)
                    if txt and txt.strip():
                        seller_val = txt.strip()
                        break
        except Exception:
            pass

        # 4. Extracción de Disponibilidad
        try:
            avail_selectors = [
                "#availability",
                "#outOfStock",
                ".a-color-price"
            ]
            for sel in avail_selectors:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    txt = await loc.text_content(timeout=2000)
                    if txt and txt.strip():
                        avail_val = txt.strip()
                        break
        except Exception:
            pass

        estado = "OK" if (price_val != "N/D" or seller_val != "N/D") else "Sin Buybox / Layout alternativo"

        return {
            "ASIN": asin,
            "Estado": estado,
            "Precio": price_val,
            "Vendedor": seller_val,
            "Disponibilidad": avail_val
        }

    except Exception as e:
        print(f"Error procesando ASIN {asin}: {str(e)}")
        return {
            "ASIN": asin,
            "Estado": f"Error: {str(e)}",
            "Precio": "N/D",
            "Vendedor": "N/D",
            "Disponibilidad": "N/D"
        }

async def main():
    print("--- INICIANDO PROCESO DE SCRAPING ---")
    if not os.path.exists(INPUT_FILE):
        raise FileNotFoundError(f"❌ No existe {INPUT_FILE}")

    df_input = pd.read_excel(INPUT_FILE)
    col_asin = [c for c in df_input.columns if str(c).strip().upper() == 'ASIN']
    if not col_asin:
        raise ValueError(f"❌ Columna ASIN no encontrada. Cabeceras: {list(df_input.columns)}")

    asins = df_input[col_asin[0]].dropna().astype(str).str.strip().tolist()
    print(f"✅ ASINs a procesar: {asins}")

    results = []

    async with async_playwright() as p:
        # Configurar Chromium sin las banderas habituales de automatización
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="es-ES",
            timezone_id="Europe/Madrid"
        )

        # Ocultar propiedad navigator.webdriver
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        page = await context.new_page()

        for asin in asins:
            print(f"Procesando ASIN: {asin}...")
            data = await scrape_buybox(page, asin)
            print(f" -> Resultado: {data['Estado']} | Precio: {data['Precio']} | Vendedor: {data['Vendedor']}")
            results.append(data)
            await asyncio.sleep(3) # Pausa entre peticiones

        await browser.close()

    # Guardar Excel de salida
    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    display_date = now.strftime("%Y-%m-%d %H:%M:%S")
    
    output_filename = f"resultado_{timestamp_str}.xlsx"
    output_path = os.path.join(RESULTS_DIR, output_filename)
    
    os.makedirs(RESULTS_DIR, exist_ok=True)
    pd.DataFrame(results).to_excel(output_path, index=False)
    print(f"✅ Excel generado: {output_path}")

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

if __name__ == "__main__":
    asyncio.run(main())
