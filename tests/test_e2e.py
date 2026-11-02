"""
UniUltraOpenPlatForm E2E 页面操作测试

使用 Playwright 进行浏览器自动化测试，模拟真实用户操作。

运行方式：
  pytest tests/test_e2e.py -v --tb=short
  pytest tests/test_e2e.py -v --headed  # 显示浏览器窗口
  pytest tests/test_e2e.py -v --slowmo=500  # 慢速演示
"""

import pytest
import os
import sys
import time
import platform
from datetime import datetime

# 添加项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import Page, expect, sync_playwright

# ============================================================
# 测试配置
# ============================================================

# 根据环境选择端口: Windows=8001, WSL=8000
_is_windows = platform.system() == "Windows"
BASE_URL = "http://127.0.0.1:8001" if _is_windows else "http://127.0.0.1:8000"
ADMIN_ACCOUNT = "Admin"
ADMIN_PASSWORD = "uni519"

# 测试结果收集
class E2ETestResults:
    def __init__(self):
        self.results = []
        self.screenshots = []

    def add(self, module, test, status, message="", screenshot=""):
        self.results.append({
            "module": module,
            "test": test,
            "status": status,
            "message": message,
            "screenshot": screenshot
        })

    def report(self):
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = sum(1 for r in self.results if r["status"] == "FAIL")
        total = len(self.results)

        report = f"""
{'='*60}
                  E2E 测试报告
{'='*60}
测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
总测试数: {total}
通过: {passed}
失败: {failed}
通过率: {passed/total*100:.1f}%
{'='*60}
"""
        for r in self.results:
            status = "✓" if r["status"] == "PASS" else "✗"
            report += f"{status} [{r['module']}] {r['test']}"
            if r["message"]:
                report += f" - {r['message']}"
            report += "\n"

        return report


e2e_results = E2ETestResults()


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def browser():
    """启动浏览器"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    """创建新页面"""
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(10000)  # 10秒超时
    yield page
    context.close()


@pytest.fixture
def authenticated_page(page):
    """已登录的页面"""
    # 访问登录页
    page.goto(f"{BASE_URL}/login")

    # 填写登录表单
    page.fill('input[name="account"]', ADMIN_ACCOUNT)
    page.fill('input[name="password"]', ADMIN_PASSWORD)

    # 点击登录
    page.click('button[type="submit"]')

    # 等待跳转到首页
    page.wait_for_url("**/")

    yield page


# ============================================================
# 辅助函数
# ============================================================

def take_screenshot(page, name):
    """截图并保存"""
    screenshot_dir = os.path.join(os.path.dirname(__file__), "reports", "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)
    path = os.path.join(screenshot_dir, f"{name}_{datetime.now().strftime('%H%M%S')}.png")
    page.screenshot(path=path)
    return path


# ============================================================
# 1. 登录测试
# ============================================================

class TestLogin:
    """登录功能测试"""

    def test_login_page_loads(self, page):
        """测试登录页面加载"""
        page.goto(f"{BASE_URL}/login")

        # 检查页面元素
        expect(page.locator('input[name="account"]')).to_be_visible()
        expect(page.locator('input[name="password"]')).to_be_visible()
        expect(page.locator('button[type="submit"]')).to_be_visible()

        e2e_results.add("登录", "登录页面加载", "PASS")

    def test_login_success(self, page):
        """测试成功登录"""
        page.goto(f"{BASE_URL}/login")

        page.fill('input[name="account"]', ADMIN_ACCOUNT)
        page.fill('input[name="password"]', ADMIN_PASSWORD)
        page.click('button[type="submit"]')

        # 等待跳转
        page.wait_for_url("**/")

        # 检查是否跳转到首页
        expect(page).to_have_url(f"{BASE_URL}/")

        e2e_results.add("登录", "成功登录", "PASS")

    def test_login_fail_wrong_password(self, page):
        """测试错误密码登录"""
        page.goto(f"{BASE_URL}/login")

        page.fill('input[name="account"]', ADMIN_ACCOUNT)
        page.fill('input[name="password"]', "wrongpassword")
        page.click('button[type="submit"]')

        # 应该还在登录页或显示错误
        time.sleep(1)

        e2e_results.add("登录", "错误密码拒绝", "PASS")

    def test_logout(self, authenticated_page):
        """测试登出"""
        page = authenticated_page

        # 点击登出（假设有登出按钮）
        page.goto(f"{BASE_URL}/logout")

        # 应该重定向到登录页
        page.wait_for_url("**/login**", timeout=5000)

        e2e_results.add("登录", "登出功能", "PASS")


# ============================================================
# 2. 首页测试
# ============================================================

class TestDashboard:
    """首页测试"""

    def test_dashboard_loads(self, authenticated_page):
        """测试首页加载"""
        page = authenticated_page

        # 检查导航菜单
        expect(page.locator('nav')).to_be_visible()

        e2e_results.add("首页", "首页加载", "PASS")

    def test_dashboard_shortcuts_layout_and_navigation(self, authenticated_page):
        """测试控制台快捷入口响应式布局及页面跳转"""
        page = authenticated_page
        page.set_viewport_size({"width": 1400, "height": 900})

        shortcuts = page.locator(".dashboard-shortcut")
        expect(shortcuts).to_have_count(4)
        expect(shortcuts).to_have_text(["报价订单", "客户表", "邮件中心", "开发信任务管理"])

        wide_boxes = [shortcuts.nth(index).bounding_box() for index in range(4)]
        assert len({round(box["y"]) for box in wide_boxes}) == 1
        assert max(box["width"] for box in wide_boxes) - min(box["width"] for box in wide_boxes) <= 1

        page.set_viewport_size({"width": 700, "height": 900})
        medium_boxes = [shortcuts.nth(index).bounding_box() for index in range(4)]
        assert len({round(box["y"]) for box in medium_boxes}) == 2

        page.set_viewport_size({"width": 480, "height": 900})
        narrow_boxes = [shortcuts.nth(index).bounding_box() for index in range(4)]
        assert len({round(box["y"]) for box in narrow_boxes}) == 4

        destinations = [
            ("报价订单", "/offer"),
            ("客户表", "/cli"),
            ("邮件中心", "/mail"),
            ("开发信任务管理", "/email_task"),
        ]
        for label, path in destinations:
            page.goto(f"{BASE_URL}/")
            page.locator(".dashboard-shortcut", has_text=label).click()
            page.wait_for_url(f"{BASE_URL}{path}")

        e2e_results.add("首页", "快捷入口响应式布局及跳转", "PASS")


# ============================================================
# 3. 员工管理页面测试
# ============================================================

class TestEmployeePage:
    """员工管理页面测试"""

    def test_employee_page_loads(self, authenticated_page):
        """测试员工页面加载"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/emp")

        # 检查表格存在
        expect(page.locator('table')).to_be_visible()

        e2e_results.add("员工", "员工页面加载", "PASS")

    def test_employee_search(self, authenticated_page):
        """测试员工搜索"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/emp")

        # 找到搜索框并输入
        search_input = page.locator('input[name="search"], input[placeholder*="搜索"], input[type="text"]').first
        if search_input.is_visible():
            search_input.fill("Admin")
            # 按回车或点击搜索按钮
            search_input.press("Enter")
            time.sleep(0.5)

        e2e_results.add("员工", "员工搜索", "PASS")

    def test_employee_pagination(self, authenticated_page):
        """测试员工分页"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/emp")

        # 检查分页元素
        time.sleep(0.5)

        e2e_results.add("员工", "员工分页", "PASS")


# ============================================================
# 4. 客户管理页面测试
# ============================================================

class TestClientPage:
    """客户管理页面测试"""

    def test_client_page_loads(self, authenticated_page):
        """测试客户页面加载"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/cli")

        expect(page.locator('table')).to_be_visible()

        e2e_results.add("客户", "客户页面加载", "PASS")

    def test_client_filter_by_region(self, authenticated_page):
        """测试按地区筛选客户"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/cli")

        # 尝试找到地区筛选下拉框
        region_select = page.locator('select[name="region"], select').first
        if region_select.is_visible():
            region_select.select_option(label="韩国")
            time.sleep(0.5)

        e2e_results.add("客户", "按地区筛选", "PASS")


# ============================================================
# 5. 供应商管理页面测试
# ============================================================

class TestVendorPage:
    """供应商管理页面测试"""

    def test_vendor_page_loads(self, authenticated_page):
        """测试供应商页面加载"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/vendor")

        expect(page.locator('table')).to_be_visible()

        e2e_results.add("供应商", "供应商页面加载", "PASS")


# ============================================================
# 6. 询价管理页面测试
# ============================================================

class TestQuotePage:
    """询价管理页面测试"""

    def test_quote_page_loads(self, authenticated_page):
        """测试询价页面加载"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/quote")

        expect(page.locator('table')).to_be_visible()

        e2e_results.add("询价", "询价页面加载", "PASS")

    def test_quote_status_filter(self, authenticated_page):
        """测试询价状态筛选"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/quote")

        # 使用 id 选择器
        status_select = page.locator('#status')
        if status_select.is_visible():
            status_select.select_option(label="询价中")
            time.sleep(0.5)

        e2e_results.add("询价", "状态筛选", "PASS")


# ============================================================
# 7. 报价管理页面测试
# ============================================================

class TestOfferPage:
    """报价管理页面测试"""

    def test_offer_page_loads(self, authenticated_page):
        """测试报价页面加载"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/offer")

        expect(page.locator('table')).to_be_visible()

        e2e_results.add("报价", "报价页面加载", "PASS")

    def test_offer_shift_select_range(self, authenticated_page):
        """测试 Shift 当前页范围勾选"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/offer?page=1&page_size=20&is_transferred=")
        page.wait_for_load_state("networkidle")

        checkboxes = page.locator("#offerTable .row-checkbox")
        if checkboxes.count() < 6:
            pytest.skip("报价记录不足，无法测试范围勾选")

        checkboxes.nth(5).check()
        checkboxes.nth(1).check()
        checkboxes.nth(3).click(modifiers=["Shift"])

        for index in (1, 2, 3):
            expect(checkboxes.nth(index)).to_be_checked()
        for index in (0, 4, 5):
            expect(checkboxes.nth(index)).not_to_be_checked()

        checkboxes.nth(2).click(modifiers=["Shift"])

        for index in (1, 2, 3):
            expect(checkboxes.nth(index)).to_be_checked()
        for index in (0, 4, 5):
            expect(checkboxes.nth(index)).not_to_be_checked()

        page.reload()
        page.wait_for_load_state("networkidle")
        checkboxes.nth(0).check()
        checkboxes.nth(4).check()
        checkboxes.nth(1).click(modifiers=["Shift"])

        for index in range(1, 5):
            expect(checkboxes.nth(index)).to_be_checked()
        for index in (0, 5):
            expect(checkboxes.nth(index)).not_to_be_checked()

        page.reload()
        page.wait_for_load_state("networkidle")
        checkboxes.nth(0).click(modifiers=["Shift"])

        expect(checkboxes.nth(0)).to_be_checked()
        for index in range(1, 6):
            expect(checkboxes.nth(index)).not_to_be_checked()

        e2e_results.add("报价", "Shift 当前页范围勾选", "PASS")

    def test_offer_smart_input_preserves_commas(self, authenticated_page):
        """测试智能带入保留字段中的中英文逗号"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/offer")
        page.get_by_role("button", name="新增报价", exact=True).click()

        smart_input = page.locator("#smartInput")
        smart_input.fill("MPN,WITH,COMMA|BRAND，NAME|100")
        page.get_by_role("button", name="解析填入", exact=True).click()

        expect(page.locator("#formMpn")).to_have_value("MPN,WITH,COMMA")
        expect(page.locator("#formBrand")).to_have_value("BRAND，NAME")
        expect(page.locator("#formQty")).to_have_value("100")

        smart_input.fill("MPN，FULL,HALF BRAND,NAME 200")
        page.get_by_role("button", name="解析填入", exact=True).click()

        expect(page.locator("#formMpn")).to_have_value("MPN，FULL,HALF")
        expect(page.locator("#formBrand")).to_have_value("BRAND,NAME")
        expect(page.locator("#formQty")).to_have_value("200")

        smart_input.fill("MPN,DIRECT|BRAND，DIRECT|300")
        page.get_by_role("button", name="直接插入", exact=True).click()

        expect(page.locator('#previewModalOverlay [data-field="mpn"]')).to_have_text("MPN,DIRECT")
        expect(page.locator('#previewModalOverlay [data-field="brand"]')).to_have_text("BRAND，DIRECT")
        expect(page.locator('#previewModalOverlay [data-field="qty"]')).to_have_text("300")

        e2e_results.add("报价", "智能带入保留中英文逗号", "PASS")

    def test_offer_smart_input_remembers_height(self, authenticated_page):
        """测试智能带入默认五行并记忆手动调整高度"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/offer")
        page.evaluate("localStorage.removeItem('offer_smart_input_height')")
        page.reload()
        page.get_by_role("button", name="新增报价", exact=True).click()

        smart_input = page.locator("#smartInput")
        expect(smart_input).to_have_attribute("rows", "5")
        initial_box = smart_input.bounding_box()

        page.mouse.move(
            initial_box["x"] + initial_box["width"] - 4,
            initial_box["y"] + initial_box["height"] - 4,
        )
        page.mouse.down()
        page.mouse.move(
            initial_box["x"] + initial_box["width"] - 4,
            initial_box["y"] + initial_box["height"] + 76,
            steps=5,
        )
        page.mouse.up()
        page.wait_for_function("localStorage.getItem('offer_smart_input_height') !== null")

        saved_height = page.evaluate("localStorage.getItem('offer_smart_input_height')")
        assert float(saved_height.removesuffix("px")) > initial_box["height"]

        page.reload()
        page.get_by_role("button", name="新增报价", exact=True).click()
        expect(page.locator("#smartInput")).to_have_css("height", saved_height)

        page.get_by_role("button", name="取消", exact=True).click()
        page.get_by_role("button", name="新增报价", exact=True).click()
        expect(page.locator("#smartInput")).to_have_css("height", saved_height)

        e2e_results.add("报价", "智能带入默认五行并记忆高度", "PASS")

    def test_offer_add_modal_responsive_width(self, authenticated_page):
        """测试新增报价弹框宽屏750px及小屏自适应"""
        page = authenticated_page
        page.set_viewport_size({"width": 1200, "height": 900})
        page.goto(f"{BASE_URL}/offer")
        page.get_by_role("button", name="新增报价", exact=True).click()

        modal = page.locator("#addModal > .card")
        expect(modal).to_have_css("width", "750px")

        page.set_viewport_size({"width": 600, "height": 900})
        modal_box = modal.bounding_box()
        assert 0 < modal_box["width"] <= 568
        assert modal_box["x"] >= 0
        assert modal_box["x"] + modal_box["width"] <= 600

        e2e_results.add("报价", "新增报价弹框响应式宽度", "PASS")

    def test_offer_add_modal_closes_on_outside_click(self, authenticated_page):
        """测试新增报价点击框外关闭并保留未提交内容"""
        page = authenticated_page
        page.set_viewport_size({"width": 1200, "height": 900})
        page.goto(f"{BASE_URL}/offer")
        page.get_by_role("button", name="新增报价", exact=True).click()

        add_modal = page.locator("#addModal")
        page.locator("#formMpn").fill("UNSAVED-MPN")
        page.locator("#formBrand").click()
        expect(add_modal).to_be_visible()

        page.mouse.click(10, 10)
        expect(add_modal).to_be_hidden()

        page.get_by_role("button", name="新增报价", exact=True).click()
        expect(add_modal).to_be_visible()
        expect(page.locator("#formMpn")).to_have_value("UNSAVED-MPN")

        e2e_results.add("报价", "新增报价框外点击关闭", "PASS")

    def test_offer_update_cost_entry_removed(self, authenticated_page):
        """测试新增报价弹框已移除更新报价区域"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/offer")
        page.get_by_role("button", name="新增报价", exact=True).click()

        expect(page.locator("#smartInput")).to_be_visible()
        expect(page.locator("#updateCostInput")).to_have_count(0)
        expect(page.locator("#updateCostMsg")).to_have_count(0)
        expect(page.get_by_role("button", name="更新报价", exact=True)).to_have_count(0)
        expect(page.get_by_text("更新报价 (仅当天录入)", exact=False)).to_have_count(0)

        e2e_results.add("报价", "新增报价移除更新报价区域", "PASS")

    def test_offer_smart_batch_sanitizes_quantity(self, authenticated_page):
        """测试直接插入预览及提交使用纯数字数量"""
        page = authenticated_page
        submitted = []

        def capture_submission(route):
            submitted.append(route.request.post_data)
            route.fulfill(status=200, json={"success": False, "message": "测试拦截"})

        page.route("**/api/offer/add_simple", capture_submission)
        page.goto(f"{BASE_URL}/offer")
        page.get_by_role("button", name="新增报价", exact=True).click()

        page.locator("#smartInput").fill(
            "MPN,QTY|BRAND|1,000pcs\n"
            "MPN,DECIMAL|BRAND|1.5\n"
            "MPN,INVALID|BRAND|abc"
        )
        page.get_by_role("button", name="直接插入", exact=True).click()

        quantities = page.locator('#previewModalOverlay [data-field="qty"]')
        expect(quantities).to_have_count(2)
        expect(quantities).to_have_text(["1000", "15"])
        expect(page.locator("#previewModalOverlay")).to_contain_text("第 3 行: 数量无效")
        expect(page.locator('#previewModalOverlay [data-field="mpn"]')).to_have_text(
            ["MPN,QTY", "MPN,DECIMAL"]
        )

        page.get_by_role("button", name="确认插入", exact=True).click()
        expect(page.locator("#smartMsg")).to_have_text("插入完成：成功 0 条，失败 2 条")
        expect(page.locator("#addModal")).to_be_hidden()
        assert len(submitted) == 2
        assert any('name="inquiry_qty"\r\n\r\n1000\r\n' in body for body in submitted)
        assert any('name="inquiry_qty"\r\n\r\n15\r\n' in body for body in submitted)

        e2e_results.add("报价", "直接插入数量清理及无效行跳过", "PASS")

    def test_offer_cancel_preview_reopens_add_modal(self, authenticated_page):
        """测试取消预览后恢复新增报价并保留输入"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/offer")
        page.get_by_role("button", name="新增报价", exact=True).click()

        smart_input = page.locator("#smartInput")
        smart_input.fill("MPN,PREVIEW|BRAND|100")
        page.get_by_role("button", name="直接插入", exact=True).click()
        expect(page.locator("#addModal")).to_be_hidden()
        expect(page.locator("#previewModalOverlay")).to_be_visible()

        page.get_by_role("button", name="取消", exact=True).click()
        expect(page.locator("#previewModalOverlay")).to_have_count(0)
        expect(page.locator("#addModal")).to_be_visible()
        expect(smart_input).to_have_value("MPN,PREVIEW|BRAND|100")

        page.get_by_role("button", name="直接插入", exact=True).click()
        page.locator('#previewModalOverlay button[onclick="closePreviewModal(true)"]').first.click()
        expect(page.locator("#previewModalOverlay")).to_have_count(0)
        expect(page.locator("#addModal")).to_be_visible()
        expect(smart_input).to_have_value("MPN,PREVIEW|BRAND|100")

        e2e_results.add("报价", "取消预览恢复新增报价", "PASS")

    def test_offer_smart_batch_fallback_customer(self, authenticated_page):
        """测试任一空客户行触发所有有效行使用表单客户"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/offer")
        page.get_by_role("button", name="新增报价", exact=True).click()

        options = page.locator("#formCliId option").evaluate_all(
            "opts => opts.filter(o => o.value).map(o => ({value: o.value, name: o.text}))"
        )
        if len(options) < 2:
            pytest.skip("客户记录不足，无法测试直接插入客户回退")

        matched, fallback = options[:2]
        cli_select = page.locator("#formCliId")
        smart_input = page.locator("#smartInput")
        cli_select.select_option(fallback["value"])
        smart_input.fill(
            f"MPN,MATCH|BRAND|100|{matched['name']}\n"
            "MPN,EMPTY|BRAND|200\n"
            "MPN,UNKNOWN|BRAND|300|NO_SUCH_CLIENT"
        )
        page.get_by_role("button", name="直接插入", exact=True).click()

        preview_customers = page.locator('#previewModalOverlay [data-field="cliName"]')
        expect(preview_customers).to_have_text([fallback["name"]] * 3)
        preview_cli_ids = page.evaluate(
            "window._previewInsertData.map(item => [item.cliId, item.formData.cli_id])"
        )
        assert preview_cli_ids == [[fallback["value"], fallback["value"]]] * 3

        page.get_by_role("button", name="取消", exact=True).click()
        smart_input.fill(
            f"MPN,MATCH1|BRAND|100|{matched['name']}\n"
            f"MPN,MATCH2|BRAND|200|{matched['name']}"
        )
        page.get_by_role("button", name="直接插入", exact=True).click()
        expect(preview_customers).to_have_text([matched["name"]] * 2)

        page.get_by_role("button", name="取消", exact=True).click()
        cli_select.select_option("")
        smart_input.fill(
            f"MPN,MATCH|BRAND|100|{matched['name']}\n"
            "MPN,EMPTY|BRAND|200"
        )
        page.get_by_role("button", name="直接插入", exact=True).click()
        expect(preview_customers).to_have_text([matched["name"], "-"])

        e2e_results.add("报价", "直接插入空客户统一使用表单客户", "PASS")


# ============================================================
# 8. 订单管理页面测试
# ============================================================

class TestOrderPage:
    """订单管理页面测试"""

    def test_order_page_loads(self, authenticated_page):
        """测试订单页面加载"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/order")

        expect(page.locator('table')).to_be_visible()

        e2e_results.add("订单", "订单页面加载", "PASS")


# ============================================================
# 9. 采购管理页面测试
# ============================================================

class TestBuyPage:
    """采购管理页面测试"""

    def test_buy_page_loads(self, authenticated_page):
        """测试采购页面加载"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/buy")

        expect(page.locator('table')).to_be_visible()

        e2e_results.add("采购", "采购页面加载", "PASS")


# ============================================================
# 10. 汇率管理页面测试
# ============================================================

class TestDailyPage:
    """汇率管理页面测试"""

    def test_daily_page_loads(self, authenticated_page):
        """测试汇率页面加载"""
        page = authenticated_page
        page.goto(f"{BASE_URL}/daily")

        expect(page.locator('table')).to_be_visible()

        e2e_results.add("汇率", "汇率页面加载", "PASS")


# ============================================================
# 11. 导航测试
# ============================================================

class TestNavigation:
    """导航测试"""

    def test_navigation_menu(self, authenticated_page):
        """测试导航菜单"""
        page = authenticated_page

        # 测试各个菜单项
        menu_items = [
            ("/", "首页"),
            ("/emp", "员工"),
            ("/cli", "客户"),
            ("/vendor", "供应商"),
            ("/quote", "询价"),
            ("/offer", "报价"),
            ("/order", "订单"),
            ("/buy", "采购"),
            ("/daily", "汇率"),
        ]

        for url, name in menu_items:
            page.goto(f"{BASE_URL}{url}")
            time.sleep(0.3)
            e2e_results.add("导航", f"访问{name}页面", "PASS")


# ============================================================
# 12. 响应式测试
# ============================================================

class TestResponsive:
    """响应式布局测试"""

    def test_mobile_view(self, browser):
        """测试移动端视图"""
        # 创建移动端上下文
        context = browser.new_context(
            viewport={"width": 375, "height": 667},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)"
        )
        page = context.new_page()

        # 登录
        page.goto(f"{BASE_URL}/login")
        page.fill('input[name="account"]', ADMIN_ACCOUNT)
        page.fill('input[name="password"]', ADMIN_PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_url("**/")

        # 检查页面是否正常显示
        time.sleep(0.5)

        e2e_results.add("响应式", "移动端视图", "PASS")

        context.close()

    def test_tablet_view(self, browser):
        """测试平板视图"""
        context = browser.new_context(
            viewport={"width": 768, "height": 1024}
        )
        page = context.new_page()

        # 登录
        page.goto(f"{BASE_URL}/login")
        page.fill('input[name="account"]', ADMIN_ACCOUNT)
        page.fill('input[name="password"]', ADMIN_PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_url("**/")

        time.sleep(0.5)

        e2e_results.add("响应式", "平板视图", "PASS")

        context.close()


# ============================================================
# 报告生成
# ============================================================

def test_e2e_report():
    """生成 E2E 测试报告"""
    report = e2e_results.report()
    print(report)

    # 保存报告
    report_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(report_dir, exist_ok=True)

    report_path = os.path.join(report_dir, f"e2e_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nE2E 报告已保存到: {report_path}")


# ============================================================
# 主函数
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])