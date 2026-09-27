import sys
import os
import random
import time
from datetime import datetime
import pandas as pd
from playwright.sync_api import sync_playwright

OUTPUT_DIR = "output"

# ... (Las funciones get_text y scrape_product se mantienen exactamente igual) ...

def main():
    if len(sys.argv) < 2:
        print("Error: No se proporcionó ningún ASIN.")
        sys.exit(1)

    raw_input = sys.argv[1]
    
    # Capturar el timestamp/req_id si se pasa como 2do argumento, o generarlo si no existe
    if len(sys.argv) > 2 and sys.argv[2].strip():
        req_id = sys.argv[2].strip()
    else:
        req_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Nombre dinámico del archivo
    output_filename = f"resultado_amazon_{req_id}.xlsx"
    output_file_path = os.path.join(OUTPUT_DIR, output_filename)

    asin_list = [
        asin.strip().upper() 
        for asin in raw_input.replace(",", " ").split() 
        if asin.strip()
    ]

    resultados = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = browser.new_context(
            locale="es-ES",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}
        )

        page = context.new_page()

        for asin in asin_list:
            resultado = scrape_product(page, asin)
            resultados.append(resultado)
            time.sleep(random.uniform(2, 4))

        browser.close()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pd.DataFrame(resultados).to_excel(output_file_path, index=False)
    print(f"Archivo generado con éxito en: {output_file_path}")

if __name__ == "__main__":
    main()