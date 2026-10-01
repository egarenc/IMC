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

# --------------------------------------------------------------------------
# CONFIGURACIÓN DE PROXY WEBSHARE
# --------------------------------------------------------------------------
PROXY_SERVER = os.environ.get("PROXY_SERVER", "http://31.59.20.176:6754")
PROXY_USERNAME = os.environ.get("PROXY_USERNAME", "lqfkvxjs")
PROXY_PASSWORD = os.environ.get("PROXY_PASSWORD", "o114si1p43m")


async def block_unnecessary_resources(route):
    """Bloquea recursos pesados para no saturar la conexión del proxy."""
    resource_type = route.request.resource_type
    url = route.request.url.lower()
    
    # Permitimos scripts y documentos HTML pero bloqueamos multimedia pesada
    if resource_type in ["image", "media", "font"] or "ads" in url or "analytics" in url:
        await route.abort()
    else:
        await route.continue_()


async def accept_cookies_if_present(page):
    """Acepta el banner de cookies si aparece."""
    try:
        cookie_btn = page.locator("#sp-cc-accept")
        if await cookie_btn.count() > 0 and await cookie_btn.is_visible():
            await cookie_btn.click(timeout=2000)
            await asyncio.sleep(1.0)
            print("🍪 Banner de cookies aceptado.")
    except Exception:
        pass


async def handle_button_challenge_if_present(page):
    """Gestiona desafíos de botón interactivo si aparecen."""
    try:
        content = await page.content()
        content_lower = content.lower()
        
        keywords = ["haz click en el botón", "seguir comprando", "continue shopping", "click the button"]
        if any(kw in content_lower for kw in keywords):
            print("🔘 Desafío de botón interactivo detectado. Intentando hacer clic...")
            button_selectors = ["button[type='submit']", "form button", "input[type='submit']"]
            for sel in button_selectors:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(timeout=2000)
                    print(f"✅ Clic realizado en botón ({sel}).")
                    await asyncio.sleep(2.0)
                    return True
    except Exception as e:
        print(f"⚠ Error al gestionar el desafío de botón: {e}")
    return False


async def solve_amazon_captcha_if_present(page):
    """Detecta e intenta resolver CAPTCHA de imagen si aparece."""
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
                    await page.fill("#captchacharacters", solution, timeout=2000)
                    await page.click("button[type='submit']", timeout=2000)
                    await asyncio.sleep(2.0)
                    print("✅ Formulario de CAPTCHA enviado.")
                    return True
    except Exception as e:
        print(f"⚠️ Excepción al intentar resolver el CAPTCHA: {e}")
    return False


async def save_diagnostic_data(page, asin, output_base_name, prefix):
    """Guarda captura PNG e independientemente el archivo HTML por si falla el renderizado."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    base_path = os.path.join(RESULTS_DIR, f"{output_base_name}_{asin}_{prefix}")
    
    # 1. Intentar guardar volcado HTML (no depende de renderizar gráficos)
    try:
        html_content = await page.content()
        html_path = f"{base_path}.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"📄 Volcado HTML de diagnóstico guardado en: {html_path}")
    except Exception as err:
        print(f"⚠️ No se pudo guardar el HTML de diagnóstico: {err}")

    # 2. Intentar captura PNG con timeout corto
    try:
        screenshot_path = f"{base_path}.png"
        await page.screenshot(path=screenshot_path, full_page=False, timeout=4000)
        print(f"📸 Captura guardada en: {screenshot_path}")
    except Exception:
        print("⚠️ No se pudo renderizar la captura PNG (Proxy lento), consulta el archivo .html generado.")


async def scrape_buybox(page, asin, output_base_name):
    url = f"https://www.amazon.es/dp/{asin}"
    try:
        print(f"🔗 Cargando ASIN {asin} a través de Webshare Proxy...")
        
        # Carga ultra rápida sin esperar a recursos secundarios
        try:
            await page.goto(url, timeout=20000, wait_until="commit")
            await asyncio.sleep(2.0)
        except Exception as goto_error:
            print(f"⚠ Tiempo de espera en respuesta inicial ({goto_error}), procesando HTML...")

        # Manejo de cookies, captcha y desafíos
        await accept_cookies_if_present(page)
        await handle_button_challenge_if_present(page)
        await solve_amazon_captcha_if_present(page)

        current_url = page.url
        title = await page.title()
        content = await page.content()
        content_lower = content.lower()

        # Comprobar si fue bloqueado
        is_captcha = "captcha" in title.lower() or "validatecaptcha" in content_lower
        is_button_block = "haz click en el botón" in content_lower or "seguir comprando" in content_lower
        is_home_redirect = current_url.rstrip('/') == "https://www.amazon.es" or "ref=nav_logo" in current_url

        if is_captcha or is_button_block or is_home_redirect:
            block_type = "CAPTCHA" if is_captcha else ("Redirección Home" if is_home_redirect else "Botón Interactivo")
            print(f"⚠️ ASIN {asin} bloqueado o redirigido ({block_type}).")
            await save_diagnostic_data(page, asin, output_base_name, "blocked")

            return {
                "ASIN": asin,
                "Estado": f"Bloqueado ({block_type})",
                "Precio": "N/D",
                "Vendedor": "N/D",
                "Disponibilidad": "N/D",
                "URL_Final": current_url
            }

        price_val = "N/D"
        seller_val = "N/D"
        avail_val = "N/D"

        # Extracción de Precio
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
                    txt = await loc.text_content(timeout=800)
                    if txt and txt.strip() and "€" in txt:
                        price_val = txt.strip()
                        break
            except Exception:
                continue

        # Extracción de Vendedor
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
                    txt = await loc.text_content(timeout=800)
                    if txt and txt.strip():
                        clean_seller = " ".join(txt.split())
                        if len(clean_seller) > 2:
                            seller_val = clean_seller
                            break
            except Exception:
                continue

        # Extracción de Disponibilidad
        avail_selectors = [
            "#availability",
            "#outOfStock",
            "#glow-ingress-block",
            "#availability span"
        ]
        for sel in avail_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    txt = await loc.text_content(timeout=800)
                    if txt and txt.strip():
                        avail_val = " ".join(txt.split())
                        break
            except Exception:
                continue

        # Clasificación del estado
        if price_val != "N/D" or seller_val != "N/D":
            estado = "OK"
        elif "no disponible" in content_lower or "currently unavailable" in content_lower:
            estado = "Producto No Disponible"
        else:
            await save_diagnostic_data(page, asin, output_base_name, "no_buybox")
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
    print("--- INICIANDO PROCESO DE SCRAPING CON PROXY WEBSHARE ---")
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

    proxy_config = {
        "server": PROXY_SERVER,
        "username": PROXY_USERNAME,
        "password": PROXY_PASSWORD
    }

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
            proxy=proxy_config,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="es-ES",
            timezone_id="Europe/Madrid"
        )

        page = await context.new_page()
        
        # Interceptamos y bloqueamos recursos no esenciales para optimizar el proxy
        await page.route("**/*", block_unnecessary_resources)

        for asin in asins:
            print(f"Procesando ASIN: {asin}...")
            data = await scrape_buybox(page, asin, output_base_name)
            print(f" -> Resultado: {data['Estado']} | Precio: {data['Precio']} | Vendedor: {data['Vendedor']}")
            results.append(data)
            
            wait_time = random.uniform(3.0, 6.0)
            print(f"⏱ Esperando {wait_time:.2f} segundos antes del siguiente ASIN...")
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
