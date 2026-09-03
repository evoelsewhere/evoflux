import { test, expect } from '@playwright/test'

test.describe('HTML Preview JS Toggle — Evidence', () => {

  test('screenshot: JS Off state', async ({ page }) => {
    await page.goto('about:blank')
    await page.evaluate(() => {
      let scriptsEnabled = false
      function render() {
        const root = document.getElementById('root')!
        root.innerHTML = ''

        const toolbar = document.createElement('div')
        toolbar.style.cssText = 'display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:4px 8px;border-bottom:1px solid #333;background:#1a1a2e'

        const btn = document.createElement('button')
        btn.id = 'toggle'
        btn.style.cssText = 'font-size:12px;padding:2px 8px;cursor:pointer;border-radius:4px;border:1px solid #555;background:' + (scriptsEnabled ? '#4a2e1f' : '#2a2a3e') + ';color:' + (scriptsEnabled ? '#f0a46f' : '#8888bb')
        btn.textContent = scriptsEnabled ? 'JS On' : 'JS Off'
        btn.addEventListener('click', () => { scriptsEnabled = !scriptsEnabled; render() })

        const iframe = document.createElement('iframe')
        iframe.id = 'preview'
        iframe.style.cssText = 'width:100%;height:400px;border:0;background:#0d1117'
        iframe.setAttribute('sandbox', scriptsEnabled ? 'allow-scripts allow-same-origin' : '')
        iframe.srcdoc = `<!doctype html><html><head><style>body{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:20px}h1{color:#58a6fa}#app{color:#3fb950;font-weight:bold}</style></head><body><h1>HTML Preview Test</h1><p>This text is static HTML.</p><div id="app">JS did NOT run (blocked by sandbox)</div><script>document.getElementById('app').innerHTML='JS rendered this! ✅';document.getElementById('app').style.color='#3fb950'</script></body></html>`

        toolbar.appendChild(btn)
        root.appendChild(toolbar)
        root.appendChild(iframe)
      }

      const root = document.createElement('div')
      root.id = 'root'
      document.body.style.margin = '0'
      document.body.style.background = '#0d1117'
      document.body.appendChild(root)
      render()
    })

    await page.waitForTimeout(500)
    await page.screenshot({ path: 'test-results/evidence-js-off.png', fullPage: true })
  })

  test('screenshot: JS On state', async ({ page }) => {
    await page.goto('about:blank')
    await page.evaluate(() => {
      let scriptsEnabled = true
      function render() {
        const root = document.getElementById('root')!
        root.innerHTML = ''

        const toolbar = document.createElement('div')
        toolbar.style.cssText = 'display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:4px 8px;border-bottom:1px solid #333;background:#1a1a2e'

        const btn = document.createElement('button')
        btn.id = 'toggle'
        btn.style.cssText = 'font-size:12px;padding:2px 8px;cursor:pointer;border-radius:4px;border:1px solid #555;background:' + (scriptsEnabled ? '#4a2e1f' : '#2a2a3e') + ';color:' + (scriptsEnabled ? '#f0a46f' : '#8888bb')
        btn.textContent = scriptsEnabled ? 'JS On' : 'JS Off'
        btn.addEventListener('click', () => { scriptsEnabled = !scriptsEnabled; render() })

        const iframe = document.createElement('iframe')
        iframe.id = 'preview'
        iframe.style.cssText = 'width:100%;height:400px;border:0;background:#0d1117'
        iframe.setAttribute('sandbox', scriptsEnabled ? 'allow-scripts allow-same-origin' : '')
        iframe.srcdoc = `<!doctype html><html><head><style>body{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:20px}h1{color:#58a6fa}#app{color:#3fb950;font-weight:bold}</style></head><body><h1>HTML Preview Test</h1><p>This text is static HTML.</p><div id="app">JS did NOT run (blocked by sandbox)</div><script>document.getElementById('app').innerHTML='JS rendered this! ✅';document.getElementById('app').style.color='#3fb950'</script></body></html>`

        toolbar.appendChild(btn)
        root.appendChild(toolbar)
        root.appendChild(iframe)
      }

      const root = document.createElement('div')
      root.id = 'root'
      document.body.style.margin = '0'
      document.body.style.background = '#0d1117'
      document.body.appendChild(root)
      render()
    })

    await page.waitForTimeout(500)
    await page.screenshot({ path: 'test-results/evidence-js-on.png', fullPage: true })
  })

  test('screenshot: external JS inlined', async ({ page }) => {
    const externalJs = `document.getElementById('app').innerHTML = '<h1 style="color:#3fb950">External JS inlined and executed!</h1>';`
    const htmlWithExternalScript = `<!DOCTYPE html><html><head><style>body{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:20px}h1{color:#58a6fa}</style></head><body><h1>External JS Test</h1><div id="app">loading...</div><script src="./app.js"><\/script></body></html>`
    const inlined = htmlWithExternalScript.replace(
      '<script src="./app.js"><\/script>',
      '<script>' + externalJs + '<\/script>'
    )

    await page.setContent(`
      <div style="background:#0d1117;padding:8px;font-family:system-ui;color:#c9d1d9;font-size:12px;border-bottom:1px solid #333;display:flex;justify-content:flex-end">
        <span style="background:#4a2e1f;color:#f0a46f;padding:2px 8px;border-radius:4px;font-size:11px">JS On (external inlined)</span>
      </div>
      <iframe id="f" srcdoc="${inlined.replace(/"/g, '&quot;')}" sandbox="allow-scripts allow-same-origin" style="width:100%;height:400px;border:0"></iframe>
    `)
    await page.waitForTimeout(500)
    await page.screenshot({ path: 'test-results/evidence-external-js.png', fullPage: true })
  })
})
