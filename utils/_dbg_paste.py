from playwright.sync_api import sync_playwright

sample_html = """<html><head><style>.red{color:red}</style></head><body>
<!--StartFragment-->
<div class="red">尊敬的 {公司名} 您好</div>
<table border="1" style="border-collapse:collapse;width:600px">
<tr><td>型号</td><td>品牌</td><td>价格</td></tr>
""" + "".join(f"<tr><td>LM317T-{i}</td><td>TI</td><td>0.{i:02d}</td></tr>" for i in range(200)) + """
</table>
<p>结尾祝福语 Best regards</p>
<img src="https://example.com/logo.png" alt="logo">
<!--EndFragment-->
</body></html>"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={'width': 1600, 'height': 900},
                              permissions=['clipboard-read', 'clipboard-write'])
    page = ctx.new_page()
    page.on('pageerror', lambda e: print('PAGEERROR:', e))
    page.goto('http://127.0.0.1:8001/login')
    page.wait_for_load_state('networkidle')
    page.fill('input[name="account"]', 'Admin')
    page.fill('input[name="password"]', 'uni519')
    page.click('button[type="submit"]')
    page.wait_for_load_state('networkidle')
    page.goto('http://127.0.0.1:8001/email_task')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(800)

    # 写入真实剪贴板（text/html + text/plain）
    page.evaluate("""async (html) => {
        const item = new ClipboardItem({
            'text/html': new Blob([html], {type: 'text/html'}),
            'text/plain': new Blob([html], {type: 'text/plain'})
        });
        await navigator.clipboard.write([item]);
    }""", sample_html)

    page.click('#taskBody')
    page.keyboard.press('Control+V')
    page.wait_for_timeout(1500)

    result = page.evaluate("""() => {
        const out = document.getElementById('taskBody').innerHTML;
        return {
            outputLen: out.length,
            hasEnd: out.includes('结尾祝福语'),
            hasImg: out.includes('logo.png'),
            rowCount: (out.match(/LM317T/g) || []).length,
            outputHead: out.substring(0, 200),
            outputTail: out.substring(out.length - 200)
        };
    }""")
    print('inputLen:', len(sample_html))
    for k, v in result.items():
        print(k, ':', v)
    browser.close()
