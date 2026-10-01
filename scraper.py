import os
import json
import asyncio
import random
from datetime import datetime
import pandas as pd
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from amazoncaptcha import AmazonCaptcha

INPUT_FILE = "input/asins.xlsx"
RESULTS_DIR = "results"
INDEX_FILE = os.path.join(RESULTS_DIR, "index.json")

async def accept_cookies_if_present(page):
    """Acepta el banner de cookies si aparece para desencadenar el renderizado completo."""
    try:
        cookie_btn = page.locator("#sp-cc-accept")
        if await cookie_btn.count() > 0 and await cookie_btn.is_visible():
            await cookie_btn.click()
            await asyncio.sleep(random.uniform(1.0, 2.0))
            print("🍪 Banner de cookies aceptado.")
    except Exception:
        pass

async def solve_amazon_captcha_if_present(page):
    """Detecta si Amazon muestra la pantalla de CAPTCHA y lo resuelve automáticamente."""
    try:
        captcha_img = page.locator("form[action='/errors/validateCaptcha'] img")
        if await captcha_img.count() > 0:
            print("🧩 CAPTCHA de imagen detectado. Intentando resolver con IA local...")
            img_url = await captcha_img.get_attribute("src")
            
            if img_url:
                captcha = AmazonCaptcha.from_driver_url(img_url)
                solution = captcha.solve()
                print(f"🔑 Solución calculada por amazoncaptcha: {solution}")

                if solution and solution != "Not solved":
                    await page.fill("#captchacharacters", solution)
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    await page.click("button[type='submit']")
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(random.uniform(2.0, 3.5))
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
        await asyncio.sleep(random.uniform(2.0, 4.0))

        # 1. Aceptar banner de cookies si existe
        await accept_cookies_if_present(page)

        # 2. Verificar e intentar resolver CAPTCHA de imagen si aparece
        captcha_solved = await solve_amazon_captcha_if_present(page)
        if captcha_solved:
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(random.uniform(2.0, 3.5))

        # 3. Comprobar si seguimos bloqueados
        title = await page.title()
        content = await page.content()
        
        if "captcha" in title.lower() or "validateCaptcha" in content:
            print(f"⚠️ El CAPTCHA no se pudo resolver para el ASIN: {asin}")
            return {
                "ASIN": asin,
                "Estado": "Bloqueado (CAPTCHA)",
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

        # 4. Extracción de Precio con lista ampliada de selectores
        price_selectors = [
            "#corePrice_feature_div .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-offscreen",
            ".apexPriceToPay .a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            "#price_inside_buybox",
            "#buyNewSection .a-color-price",
            "#a-autoid-0-announce .a-color-price",
            ".a-price .a-offscreen",
            "span.a-price span.a-offscreen"
        ]
        
        for sel in price_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    txt = await loc.text_content(timeout=1500)
                    if txt and txt.strip() and "€" in txt:
                        price_val = txt.strip()
                        break
            except Exception:
                continue

        # 5. Extracción de Vendedor con lista ampliada
        seller_selectors = [
            "#merchant-info",
            "#sellerProfileTriggerId",
            "#shipsFromSoldBy_feature_div",
            "#tabular-buybox",
            "#tabular-buybox .tabular-buybox-text[s-seller]",
            "#fbaProfileTriggerId",
            "#merchant-info a"
        ]
        
        for sel in seller_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    txt = await loc.text_content(timeout=1500)
                    if txt and txt.strip():
                        clean_seller = " ".join(txt.split())
                        if len(clean_seller) > 2:
                            seller_val = clean_seller
                            break
            except Exception:
                continue

        # 6. Extracción de Disponibilidad
        avail_selectors = [
            "#availability",
            "#outOfStock",
            ".a-color-price",
            "#availability span"
        ]
        for sel in avail_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    txt = await loc.text_content(timeout=1500)
                    if txt and txt.strip():
                        avail_val = " ".join(txt.split())
                        break
            except Exception:
                continue

        # Evaluación del estado del producto
        if price_val != "N/D" or seller_val != "N/D":
            estado = "OK"
        elif "no disponible" in content.lower() or "currently unavailable" in content.lower():
            estado = "Producto No Disponible"
        else:
            estado = "Sin Buybox / Layout alternativo"
            print(f"🔍 DEBUG ASIN {asin}: Título de página: '{title}'")

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

    # Uso de Stealth().use_async() para aplicar automáticamente las reglas stealth a todo el navegador
    async with Stealth().use_async(async_playwright()) as p:
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

        page = await context.new_page()

        for asin in asins:
            print(f"Procesando ASIN: {asin}...")
            data = await scrape_buybox(page, asin)
            print(f" -> Resultado: {data['Estado']} | Precio: {data['Precio']} | Vendedor: {data['Vendedor']}")
            results.append(data)
            
            # Pausa aleatoria entre 4 y 9 segundos
            wait_time = random.uniform(4.0, 9.0)
            print(f"⏱️ Esperando {wait_time:.2f} segundos antes del siguiente ASIN...")
            await asyncio.sleep(wait_time)

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

    # Limpieza automática del archivo de entrada al final
    if os.path.exists(INPUT_FILE):
        try:
            os.remove(INPUT_FILE)
            print(f"🧹 Archivo de entrada {INPUT_FILE} eliminado correctamente tras generar los resultados.")
        except Exception as e:
            print(f"⚠️ No se pudo eliminar el archivo de entrada: {e}")

if __name__ == "__main__":
    asyncio.run(main())
