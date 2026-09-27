// ... dentro de processAndTrigger() ...

// Generar timestamp único para esta ejecución
const now = new Date();
const timestamp = now.getFullYear().toString() +
    String(now.getMonth() + 1).padStart(2, '0') +
    String(now.getDate()).padStart(2, '0') + '_' +
    String(now.getHours()).padStart(2, '0') +
    String(now.getMinutes()).padStart(2, '0') +
    String(now.getSeconds()).padStart(2, '0');

const expectedFileName = `resultado_amazon_${timestamp}.xlsx`;
const publicDownloadUrl = `https://raw.githubusercontent.com/${OWNER}/${REPO}/despliegue-excel/${expectedFileName}`;

// Enviar dispatch a GitHub incluyendo el timestamp en el payload
const response = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/dispatches`, {
    method: 'POST',
    headers: {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': `token ${token}`,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({
        event_type: 'run-scraper',
        client_payload: { 
            url: asins.join(' '),
            req_id: timestamp 
        }
    })
});

if (!response.ok) throw new Error('Error al conectar con la API de GitHub.');

// ... Monitoreo de la ejecución ...
showStatus('Iniciando servidor de scraping...', 'info');
const runId = await waitForRunToStart(OWNER, REPO, token, startTime);

showStatus('Extrayendo datos de Amazon...', 'info');
await waitForRunCompletion(OWNER, REPO, token, runId);

// Mostrar botón con el nombre exacto que incluye el timestamp
showStatus(`
    🎉 <strong>¡Extracción completada con éxito!</strong><br><br>
    Archivo generado: <code>${expectedFileName}</code><br><br>
    <a href="${publicDownloadUrl}" class="btn-download" target="_blank" download="${expectedFileName}">
       📥 Descargar ${expectedFileName}
    </a>
`, 'success');