import os
import json
import asyncio
from datetime import datetime
import pandas as pd
from playwright.async_api import async_playwright
from amazoncaptcha import AmazonCaptcha

INPUT_FILE = "input/asins.xlsx"
RESULTS_DIR = "results"
INDEX_FILE = os.path.join(RESULTS_DIR, "index.json")

async def solve_amazon_captcha_if_present(page):
    """Detecta si Amazon muestra la pantalla de CAPTCHA y lo resuelve automáticamente."""
    try:
        # Selector de la imagen del CAPTCHA en el formulario de Amazon
        captcha_img = page.locator("form[action='/errors/validateCaptcha'] img")
        if await captcha_img.count() > 0:
            print("🧩 CAPTCHA de imagen detectado. Intentando resolver con IA local...")
            img_url = await captcha_img.get_attribute("src")
            
            if img_url:
                # La librería descifra el texto de la imagen
                captcha = AmazonCaptcha.from_driver_url(img_url)
                solution = captcha.solve()
                print(f"🔑 Solución calculada por amazoncaptcha: {solution}")

                if solution and solution != "Not solved":
                    # Escribir solución en el input de la página
                    await page.fill("#captchacharacters", solution)
                    # Pulsar el botón de envío
                    await page.click("button[type='submit']")
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(2)
                    print("✅ Formulario de CAPTCHA enviado.")
                    return True
                else:
                    print("❌ La librería no pudo descifrar la imagen del CAPTCHA.")
    except Exception as e:
        print(f"⚠️ Excepción al intentar resolver el CAPTCHA: {e}")
    return False

async def scrape_buybox(page, asin):
    url = f"https://www.amazon.es/dp/{asin}"
    try:
        response = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # 1. Verificar e intentar resolver CAPTCHA de imagen si aparece
        captcha_solved = await solve_amazon_captcha_if_present(page)
        if captcha_solved:
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)

        # 2. Comprobar si seguimos bloqueados
        title = await page.title()
        content = await page.content()
        
        if "captcha" in title.lower() or "validateCaptcha" in content:
            print(f"⚠️ El CAPTCHA no se pudo resolver para el ASIN: {asin}")
            return {
                "ASIN": asin,
                "Estado": "Bloqueado (CAPTCHA no resuelto)",
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

        # 3. Extracción de Precio con selectores alternativos
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

        # 4. Extracción de Vendedor con selectores alternativos
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

        # 5. Extracción de Disponibilidad
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

        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        page = await context.new_page()

        for asin in asins:
            print(f"Procesando ASIN: {asin}...")
            data = await scrape_buybox(page, asin)
            print(f" -> Resultado: {data['Estado']} | Precio: {data['Precio']} | Vendedor: {data['Vendedor']}")
            results.append(data)
            await asyncio.sleep(3)

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

    # Limpieza automática del archivo de entrada
    if os.path.exists(INPUT_FILE):
        try:
            os.remove(INPUT_FILE)
            print(f"🧹 Archivo de entrada {INPUT_FILE} eliminado correctamente tras generar los resultados.")
        except Exception as e:
            print(f"⚠️ No se pudo eliminar el archivo de entrada: {e}")

if __name__ == "__main__":
    asyncio.run(main())
