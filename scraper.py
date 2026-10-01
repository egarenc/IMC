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
    """Acepta el banner de cookies si aparece."""
    try:
        cookie_btn = page.locator("#sp-cc-accept")
        if await cookie_btn.count() > 0 and await cookie_btn.is_visible():
            await cookie_btn.click()
            await asyncio.sleep(random.uniform(1.0, 2.0))
            print("🍪 Banner de cookies aceptado.")
    except Exception:
        pass

async def handle_button_challenge_if_present(page):
    """Detecta la pantalla con botón de 'seguir comprando' e intenta pulsar el botón."""
    try:
        content = await page.content()
        content_lower = content.lower()
        
        # Palabras clave habituales en el bloqueo por botón de Amazon
        keywords = ["haz click en el botón", "seguir comprando", "continue shopping", "click the button"]
        if any(kw in content_lower for kw in keywords):
            print("🔘 Desafío de botón interactivo detectado. Intentando hacer clic...")
            
            # Buscar el botón por distintos selectores habituales
            button_selectors = [
                "button[type='submit']",
                "form button",
                "input[type='submit']",
                "a.a-button-text",
                ".a-button-input"
            ]
            
            for sel in button_selectors:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    print(f"✅ Clic realizado en botón ({sel}). Esperando recarga...")
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(random.uniform(3.0, 5.0))
                    return True
    except Exception as e:
        print(f"⚠️️ Error al gestionar el desafío de botón: {e}")
    return False

async def solve_amazon_captcha_if_present(page):
    """Detecta si Amazon muestra CAPTCHA de imagen y lo resuelve con amazoncaptcha."""
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

async def scrape_buybox(page, asin, output_base_name):
    url = f"https://www.amazon.es/dp/{asin}"
    try:
        response = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(2.0, 4.0))

        # 1. Aceptar banner de cookies si existe
        await accept_cookies_if_present(page)

        # 2. Gestionar desafío de botón si aparece
        await handle_button_challenge_if_present(page)

        # 3. Gestionar CAPTCHA de imagen si aparece
        await solve_amazon_captcha_if_present(page)

        # Obtener datos de depuración (URL final, título y HTML)
        current_url = page.url
        title = await page.title()
        content = await page.content()
        content_lower = content.lower()

        # 4. Comprobar si seguimos en pantalla de bloqueo
        is_captcha = "captcha" in title.lower() or "validatecaptcha" in content_lower
        is_button_block = "haz click en el botón" in content_lower or "seguir comprando" in content_lower

        if is_captcha or is_button_block:
            block_type = "CAPTCHA Imagen" if is_captcha else "Botón Interactivo"
            print(f"⚠️ ASIN {asin} bloqueado ({block_type}). URL: {current_url}")
            
            # Guardar captura de pantalla
            os.makedirs(RESULTS_DIR, exist_ok=True)
            screenshot_path = os.path.join(RESULTS_DIR, f"{output_base_name}_{asin}.png")
            try:
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"📸 Captura del bloqueo guardada en: {screenshot_path}")
            except Exception as e_img:
                print(f"⚠️ No se pudo guardar la captura de pantalla: {e_img}")

            return {
                "ASIN": asin,
                "Estado": f"Bloqueado ({block_type})",
                "Precio": "N/D",
                "Vendedor": "N/D",
                "Disponibilidad": "N/D",
                "URL_Final": current_url
            }

        if response and response.status != 200:
            return {
                "ASIN": asin,
                "Estado": f"Error HTTP {response.status}",
                "Precio": "N/D",
                "Vendedor": "N/D",
                "Disponibilidad": "N/D",
                "URL_Final": current_url
            }

        price_val = "N/D"
        seller_val = "N/D"
        avail_val = "N/D"

        # 5. Extracción de Precio
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

        # 6. Extracción de Vendedor
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

        # 7. Extracción de Disponibilidad
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

        # Evaluación final del estado
        if price_val != "N/D" or seller_val != "N/D":
            estado = "OK"
        elif "no disponible" in content_lower or "currently unavailable" in content_lower:
            estado = "Producto No Disponible"
        else:
            estado = "Sin Buybox / Layout alternativo"

        return {
            "ASIN": asin,
            "Estado": estado,
            "Precio": price_val,
            "Vendedor": seller_val,
            "Disponibilidad": avail_val,
            "URL_Final": current_url
        }

    except Exception as e:
        print(f"Error procesando ASIN {asin}: {str(e)}")
        return {
            "ASIN": asin,
            "Estado": f"Error: {str(e)}",
            "Precio": "N/D",
            "Vendedor": "N/D",
            "Disponibilidad": "N/D",
            "URL_Final": page.url if page else url
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

    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    display_date = now.strftime("%Y-%m-%d %H:%M:%S")
    output_base_name = f"resultado_{timestamp_str}"

    results = []

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
            data = await scrape_buybox(page, asin, output_base_name)
            print(f" -> Resultado: {data['Estado']} | Precio: {data['Precio']} | URL: {data['URL_Final']}")
            results.append(data)
            
            wait_time = random.uniform(4.0, 9.0)
            print(f"⏱️ Esperando {wait_time:.2f} segundos antes del siguiente ASIN...")
            await asyncio.sleep(wait_time)

        await browser.close()

    # Guardar Excel de salida
    output_filename = f"{output_base_name}.xlsx"
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

    # Limpieza del archivo de entrada
    if os.path.exists(INPUT_FILE):
        try:
            os.remove(INPUT_FILE)
            print(f"🧹 Archivo {INPUT_FILE} eliminado tras procesar.")
        except Exception as e:
            print(f"⚠️ No se pudo eliminar el archivo de entrada: {e}")

if __name__ == "__main__":
    asyncio.run(main())
