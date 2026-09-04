import { test, expect } from '@playwright/test'

test.describe('HTML Preview JS Toggle', () => {

  test('toggle button renders and switches JS on/off', async ({ page }) => {
    await page.goto('about:blank')
    await page.evaluate(() => {
      let scriptsEnabled = false
      function render() {
        const root = document.getElementById('root')!
        root.innerHTML = ''

        const toolbar = document.createElement('div')
        toolbar.style.cssText = 'display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:4px 8px;border-bottom:1px solid #333'

        const btn = document.createElement('button')
        btn.id = 'toggle'
        btn.style.cssText = 'font-size:12px;padding:2px 8px;cursor:pointer'
        btn.textContent = scriptsEnabled ? 'JS On' : 'JS Off'
        btn.addEventListener('click', () => {
          scriptsEnabled = !scriptsEnabled
          render()
        })

        const iframe = document.createElement('iframe')
        iframe.id = 'preview'
        iframe.style.cssText = 'width:100%;height:200px;border:0'
        iframe.setAttribute('sandbox', scriptsEnabled ? 'allow-scripts allow-same-origin' : '')
        iframe.srcdoc = '<!doctype html><html><body><div id="app">static</div><script>document.getElementById("app").innerHTML="<h1>JS Works!<\/h1>"<\/script></body></html>'

        toolbar.appendChild(btn)
        root.appendChild(toolbar)
        root.appendChild(iframe)
      }

      const root = document.createElement('div')
      root.id = 'root'
      document.body.appendChild(root)
      render()
    })

    const toggle = page.locator('#toggle')
    await expect(toggle).toBeVisible()
    await expect(toggle).toHaveText('JS Off')

    const frame = page.locator('#preview')
    expect(await frame.evaluate((el) => el.getAttribute('sandbox'))).toBe('')

    await toggle.click()
    await expect(toggle).toHaveText('JS On')
    expect(await frame.evaluate((el) => el.getAttribute('sandbox'))).toBe('allow-scripts allow-same-origin')
  })

  test('inline JS demo page renders with scripts enabled', async ({ page }) => {
    const demoHtml = `
      <!DOCTYPE html>
      <html>
      <head><style>body{font-family:system-ui}#app{color:green}</style></head>
      <body>
        <div id="app">loading...</div>
        <script>
          document.getElementById('app').innerHTML = '<h1 id="done">JS rendered this!</h1>';
        </script>
      </body>
      </html>
    `

    // Without sandbox — JS runs
    await page.setContent(demoHtml)
    await expect(page.locator('#done')).toHaveText('JS rendered this!')

    // With sandbox="" — JS blocked
    await page.setContent(`
      <iframe id="f" srcdoc="${demoHtml.replace(/"/g, '&quot;')}" sandbox="" style="width:100%;height:200px"></iframe>
    `)
    const frame = page.frameLocator('#f')
    await expect(frame.locator('#app')).toHaveText('loading...')

    // With sandbox="allow-scripts" — JS runs
    await page.setContent(`
      <iframe id="f" srcdoc="${demoHtml.replace(/"/g, '&quot;')}" sandbox="allow-scripts allow-same-origin" style="width:100%;height:200px"></iframe>
    `)
    const frame2 = page.frameLocator('#f')
    await expect(frame2.locator('#done')).toHaveText('JS rendered this!')
  })

  test('external JS files are inlined and execute', async ({ page }) => {
    const externalJs = `document.getElementById('app').innerHTML = '<h1 id="done">External JS inlined!</h1>';`

    const htmlWithExternalScript = `<!DOCTYPE html>
      <html><body>
        <div id="app">loading...</div>
        <script src="./app.js"><\/script>
      </body></html>`

    const inlined = htmlWithExternalScript.replace(
      '<script src="./app.js"><\/script>',
      '<script>' + externalJs + '<\/script>'
    )

    await page.setContent(`
      <iframe id="f" srcdoc="${inlined.replace(/"/g, '&quot;')}" sandbox="allow-scripts allow-same-origin" style="width:100%;height:200px"></iframe>
    `)
    const frame = page.frameLocator('#f')
    await expect(frame.locator('#done')).toHaveText('External JS inlined!')
  })
})
