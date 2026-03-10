"""
Document Generator - 统一的文档生成模块

包含 CI (Commercial Invoice)、PI (Proforma Invoice) 等文档生成功能。
供 main.py 和 skill 脚本共同调用。
"""

import os
from datetime import datetime
from copy import copy

try:
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.drawing.image import Image
except ImportError:
    openpyxl = None

from Sills.base import get_db_connection, get_exchange_rates


# ============================================================
# 样式配置 - 商务蓝风格
# ============================================================

COLOR_HEADER_BG = "1E3A5F"
COLOR_HEADER_FONT = "FFFFFF"
COLOR_ROW_ODD = "F8FAFC"
COLOR_ROW_EVEN = "FFFFFF"
COLOR_TOTAL_BG = "1E3A5F"
COLOR_TOTAL_FONT = "FFFFFF"
COLOR_TOTAL_AMOUNT = "DC2626"

BORDER_THIN = Border(
    left=Side(style='thin', color='D1D5DB'),
    right=Side(style='thin', color='D1D5DB'),
    top=Side(style='thin', color='D1D5DB'),
    bottom=Side(style='thin', color='D1D5DB')
)

BORDER_MEDIUM = Border(
    left=Side(style='medium', color='1E3A5F'),
    right=Side(style='medium', color='1E3A5F'),
    top=Side(style='medium', color='1E3A5F'),
    bottom=Side(style='medium', color='1E3A5F')
)


# ============================================================
# 数据查询函数
# ============================================================

def get_orders_for_document(order_ids):
    """获取订单列表（用于生成CI/PI文档）"""
    if not order_ids:
        return []
    placeholders = ','.join(['?'] * len(order_ids))
    with get_db_connection() as conn:
        rows = conn.execute(f"""
            SELECT o.order_id, o.order_no, o.order_date, o.cli_id,
                   o.inquiry_mpn, o.inquiry_brand, o.price_rmb, o.price_kwr, o.price_usd,
                   o.offer_id, o.cost_price_rmb,
                   c.cli_name, c.cli_name_en, c.contact_name, c.address, c.email, c.phone,
                   c.cli_full_name, c.region,
                   off.quoted_qty, off.date_code, off.delivery_date, off.inquiry_qty
            FROM uni_order o
            LEFT JOIN uni_cli c ON o.cli_id = c.cli_id
            LEFT JOIN uni_offer off ON o.offer_id = off.offer_id
            WHERE o.order_id IN ({placeholders})
            ORDER BY o.order_id
        """, order_ids).fetchall()
        return [dict(r) for r in rows]


def get_offers_for_document(offer_ids):
    """获取报价列表（用于生成韩文报价单）"""
    if not offer_ids:
        return []
    placeholders = ','.join(['?'] * len(offer_ids))
    with get_db_connection() as conn:
        rows = conn.execute(f"""
            SELECT o.offer_id, o.offer_no, o.offer_date, o.cli_id,
                   o.quoted_mpn, o.quoted_brand, o.offer_price_rmb, o.offer_price_usd,
                   o.quoted_qty, o.date_code, o.delivery_date, o.inquiry_qty, o.inquiry_mpn,
                   c.cli_name, c.cli_name_en, c.contact_name, c.address, c.email, c.phone,
                   c.cli_full_name, c.region
            FROM uni_offer o
            LEFT JOIN uni_cli c ON o.cli_id = c.cli_id
            WHERE o.offer_id IN ({placeholders})
            ORDER BY o.offer_id
        """, offer_ids).fetchall()
        return [dict(r) for r in rows]


# ============================================================
# CI 生成 - 美元版
# ============================================================

def generate_ci_us(order_ids, output_base=None, template_dir=None):
    """
    生成美元版 Commercial Invoice

    Args:
        order_ids: 订单ID列表
        output_base: 输出基础目录（可选）
        template_dir: 模板目录（可选）

    Returns:
        tuple: (success: bool, result: dict or error_message: str)
    """
    if openpyxl is None:
        return False, "缺少依赖: 请安装 openpyxl -> pip install openpyxl"

    if not order_ids:
        return False, "未提供订单编号"

    orders = get_orders_for_document(order_ids)
    if not orders:
        return False, f"订单编号 {order_ids} 不存在"

    cli_names = set(o.get("cli_name") or "未知客户" for o in orders)
    if len(cli_names) > 1:
        return False, f"订单属于不同客户 ({', '.join(cli_names)})，无法生成同一份CI"

    cli_name = list(cli_names)[0]

    # 确定输出目录
    project_root = os.environ.get('UNIULTRA_PROJECT_ROOT',
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if not output_base:
        output_base = os.environ.get('UNIULTRA_OUTPUT_DIR')
    if not output_base:
        output_base = os.path.join(project_root, "Trans")

    if not template_dir:
        template_dir = os.path.join(project_root, "templates", "ci_us")

    now = datetime.now()
    date_dir = now.strftime("%Y%m%d")
    invoice_no = now.strftime("UNI%Y%m%d%H%M%S")

    output_dir = os.path.join(output_base, cli_name, date_dir)
    output_filename = f"COMMERCIAL INVOICE_{cli_name}_{invoice_no}.xlsx"
    output_path = os.path.join(output_dir, output_filename)

    # 生成文档
    return _generate_ci_us_excel(orders, template_dir, output_path)


def _generate_ci_us_excel(orders, template_dir, output_path):
    """生成美元版CI Excel文件"""
    data_count = len(orders)
    first_order = orders[0]
    now = datetime.now()

    header_path = os.path.join(template_dir, "CI_template_header_US.xlsx")
    footer_path = os.path.join(template_dir, "CI_template_footer_US.xlsx")

    if not os.path.exists(header_path):
        return False, f"Header模板不存在: {header_path}"
    if not os.path.exists(footer_path):
        return False, f"Footer模板不存在: {footer_path}"

    wb = openpyxl.load_workbook(header_path)
    ws = wb.active

    # 填写头部信息
    invoice_no = now.strftime("UNI%Y%m%d%H%M")
    ws['B2'] = invoice_no
    ws['F2'] = now.strftime("%Y-%m-%d")

    cli_name_en = first_order.get("cli_name_en", "") or first_order.get("cli_name", "")
    ws['B9'] = cli_name_en
    ws['F9'] = first_order.get("contact_name", "") or ""
    ws['B10'] = first_order.get("region", "") or "USA"
    ws['F10'] = first_order.get("phone", "") or ""
    ws['B11'] = first_order.get("address", "") or ""

    # 动态生成数据行
    data_start_row = 13
    template_data_rows = 3

    if data_count > template_data_rows:
        extra_rows = data_count - template_data_rows
        ws.insert_rows(data_start_row + template_data_rows, extra_rows)
        for i in range(extra_rows):
            src_row = data_start_row + template_data_rows - 1
            dst_row = data_start_row + template_data_rows + i
            for col in range(1, 8):
                src_cell = ws.cell(row=src_row, column=col)
                dst_cell = ws.cell(row=dst_row, column=col)
                if src_cell.has_style:
                    dst_cell.font = copy(src_cell.font)
                    dst_cell.border = copy(src_cell.border)
                    dst_cell.fill = copy(src_cell.fill)
                    dst_cell.number_format = src_cell.number_format
                    dst_cell.protection = copy(src_cell.protection)
                    dst_cell.alignment = copy(src_cell.alignment)
            if ws.row_dimensions[src_row].height:
                ws.row_dimensions[dst_row].height = ws.row_dimensions[src_row].height

    # 填充数据
    total_qty = 0
    total_amount = 0

    for idx, order in enumerate(orders):
        row = data_start_row + idx
        ws.cell(row=row, column=1).value = idx + 1
        ws.cell(row=row, column=2).value = "集成电路/IC"
        ws.cell(row=row, column=3).value = order.get("inquiry_mpn", "") or ""
        ws.cell(row=row, column=4).value = "8542399000"

        qty = order.get("quoted_qty") or order.get("inquiry_qty") or 0
        try:
            qty = int(qty)
        except:
            qty = 0
        ws.cell(row=row, column=5).value = qty
        ws.cell(row=row, column=5).number_format = '#,##0'
        total_qty += qty

        price_usd = float(order.get("price_usd") or 0)
        ws.cell(row=row, column=6).value = price_usd
        ws.cell(row=row, column=6).number_format = '#,##0.00'

        total = price_usd * qty
        ws.cell(row=row, column=7).value = total if total else 0
        ws.cell(row=row, column=7).number_format = '#,##0.00'
        total_amount += total

    # 追加 Footer
    footer_start_row = data_start_row + data_count
    wb_footer = openpyxl.load_workbook(footer_path)
    ws_footer = wb_footer.active

    for src_row in range(1, 4):
        dst_row = footer_start_row + src_row - 1
        for col in range(1, 8):
            src_cell = ws_footer.cell(row=src_row, column=col)
            dst_cell = ws.cell(row=dst_row, column=col)
            dst_cell.value = src_cell.value
            if src_cell.has_style:
                dst_cell.font = copy(src_cell.font)
                dst_cell.border = copy(src_cell.border)
                dst_cell.fill = copy(src_cell.fill)
                dst_cell.number_format = src_cell.number_format
                dst_cell.protection = copy(src_cell.protection)
                dst_cell.alignment = copy(src_cell.alignment)
        if ws_footer.row_dimensions[src_row].height:
            ws.row_dimensions[dst_row].height = ws_footer.row_dimensions[src_row].height

    ws.cell(row=footer_start_row, column=5).value = total_qty
    ws.cell(row=footer_start_row, column=5).number_format = '#,##0'
    ws.cell(row=footer_start_row + 1, column=7).value = total_amount
    ws.cell(row=footer_start_row + 1, column=7).number_format = '#,##0.00'

    # 复制印章图片
    if ws_footer._images:
        img = ws_footer._images[0]
        new_img = Image(img.ref)
        import zipfile
        import re
        try:
            with zipfile.ZipFile(footer_path, 'r') as z:
                drawing_content = z.read('xl/drawings/drawing1.xml').decode('utf-8')
                cx_match = re.search(r'cx="(\d+)"', drawing_content)
                cy_match = re.search(r'cy="(\d+)"', drawing_content)
                if cx_match and cy_match:
                    new_img.width = int(cx_match.group(1)) / 9525
                    new_img.height = int(cy_match.group(1)) / 9525
        except:
            new_img.width = img.width
            new_img.height = img.height
        ws.add_image(new_img, f'C{footer_start_row + 2}')

    last_row = footer_start_row + 2
    ws.print_area = f"$A$1:$G${last_row}"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    wb.save(output_path)

    return True, {
        "excel_path": output_path,
        "invoice_no": invoice_no,
        "total_qty": total_qty,
        "total_amount": total_amount,
        "cli_name": first_order.get("cli_name", ""),
        "count": data_count
    }


# ============================================================
# PI 生成
# ============================================================

def generate_pi(order_ids, output_base=None, template_dir=None):
    """
    生成 Proforma Invoice

    Args:
        order_ids: 订单ID列表
        output_base: 输出基础目录（可选）
        template_dir: 模板目录（可选）

    Returns:
        tuple: (success: bool, result: dict or error_message: str)
    """
    if openpyxl is None:
        return False, "缺少依赖: 请安装 openpyxl -> pip install openpyxl"

    if not order_ids:
        return False, "未提供订单编号"

    orders = get_orders_for_document(order_ids)
    if not orders:
        return False, f"订单编号 {order_ids} 不存在"

    cli_names = set(o.get("cli_name") or "未知客户" for o in orders)
    if len(cli_names) > 1:
        return False, f"订单属于不同客户 ({', '.join(cli_names)})，无法生成同一份PI"

    cli_name = list(cli_names)[0]

    # 确定输出目录
    project_root = os.environ.get('UNIULTRA_PROJECT_ROOT',
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if not output_base:
        output_base = os.environ.get('UNIULTRA_OUTPUT_DIR')
    if not output_base:
        output_base = os.path.join(project_root, "Trans")

    if not template_dir:
        template_dir = os.path.join(project_root, "templates", "pi")

    now = datetime.now()
    date_dir = now.strftime("%Y%m%d")
    invoice_no = now.strftime("UNI%Y%m%d%H%M%S")

    output_dir = os.path.join(output_base, cli_name, date_dir)
    output_filename = f"Proforma Invoice_{cli_name}_{invoice_no}.xlsx"
    output_path = os.path.join(output_dir, output_filename)

    # 获取汇率
    krw_val, _ = get_exchange_rates()

    # 计算KWR价格
    for order in orders:
        price_kwr = order.get("price_kwr")
        if not price_kwr or float(price_kwr or 0) == 0:
            price_rmb = order.get("price_rmb")
            if price_rmb and float(price_rmb or 0) > 0:
                price_kwr = round(float(price_rmb) * krw_val, 1)
            else:
                price_kwr = 0
        else:
            price_kwr = float(price_kwr)
        order["calculated_price_kwr"] = price_kwr

    return _generate_pi_excel(orders, template_dir, output_path)


def _generate_pi_excel(orders, template_dir, output_path):
    """生成PI Excel文件"""
    data_count = len(orders)
    first_order = orders[0]
    now = datetime.now()

    # 查找模板文件
    template_path = None
    if os.path.isdir(template_dir):
        for f in os.listdir(template_dir):
            if f.endswith(".xlsx") and not f.startswith("~"):
                template_path = os.path.join(template_dir, f)
                break

    if not template_path or not os.path.exists(template_path):
        return False, f"模板文件不存在于 {template_dir}"

    wb = openpyxl.load_workbook(template_path)
    ws = wb.active

    # 填写头部信息
    ws.cell(8, 4).value = now.strftime("UNI%Y%m%d%H")
    ws.cell(9, 4).value = now.strftime("%Y-%m-%d")

    cli_name_en = first_order.get("cli_name_en", "") or first_order.get("cli_name", "")
    ws.cell(12, 3).value = cli_name_en
    ws.cell(13, 3).value = first_order.get("contact_name", "") or ""
    ws.cell(14, 3).value = first_order.get("email", "") or ""
    ws.cell(15, 3).value = first_order.get("phone", "") or ""
    ws.cell(16, 3).value = first_order.get("address", "") or ""

    # 数据行处理
    header_row = 18
    first_data_row = 19
    template_data_rows = 2
    total_template_row = 21
    footer_start_row = 22

    # 保存 footer 数据
    footer_cells_data = {}
    for row in range(footer_start_row, ws.max_row + 1):
        for col in range(1, ws.max_column + 1):
            cell = ws.cell(row, col)
            if cell.value is not None or cell.font or cell.border or cell.fill:
                footer_cells_data[(row, col)] = {
                    "value": cell.value,
                    "font": copy(cell.font) if cell.font else None,
                    "border": copy(cell.border) if cell.border else None,
                    "fill": copy(cell.fill) if cell.fill else None,
                    "alignment": copy(cell.alignment) if cell.alignment else None,
                    "number_format": cell.number_format,
                }

    footer_row_heights = {}
    for row in range(footer_start_row, ws.max_row + 1):
        if ws.row_dimensions[row].height:
            footer_row_heights[row] = ws.row_dimensions[row].height

    # 调整行数
    rows_diff = data_count - template_data_rows
    if rows_diff > 0:
        ws.insert_rows(total_template_row, rows_diff)
        for i in range(rows_diff):
            new_row = total_template_row + i
            ws.row_dimensions[new_row].height = 20.0
    elif rows_diff < 0:
        ws.delete_rows(first_data_row + data_count, -rows_diff)

    actual_total_row = first_data_row + data_count
    actual_footer_start_row = actual_total_row + 1

    # 恢复 footer 数据
    for (orig_row, col), cell_data in footer_cells_data.items():
        new_row = orig_row + rows_diff
        if new_row >= actual_footer_start_row:
            cell = ws.cell(new_row, col)
            if cell_data["value"] is not None:
                cell.value = cell_data["value"]
            if cell_data["font"]:
                cell.font = cell_data["font"]
            if cell_data["border"]:
                cell.border = cell_data["border"]
            if cell_data["fill"]:
                cell.fill = cell_data["fill"]
            if cell_data["alignment"]:
                cell.alignment = cell_data["alignment"]
            if cell_data["number_format"]:
                cell.number_format = cell_data["number_format"]

    for orig_row, height in footer_row_heights.items():
        new_row = orig_row + rows_diff
        ws.row_dimensions[new_row].height = height

    # 写入数据
    for idx, order in enumerate(orders):
        row = first_data_row + idx

        ws.cell(row, 1).value = idx + 1
        ws.cell(row, 2).value = order.get("inquiry_mpn", "") or ""
        ws.cell(row, 3).value = order.get("inquiry_brand", "") or ""
        ws.cell(row, 4).value = order.get("date_code", "") or ""

        qty = order.get("quoted_qty") or order.get("inquiry_qty") or ""
        ws.cell(row, 5).value = qty
        if qty:
            ws.cell(row, 5).number_format = '#,##0'

        ws.cell(row, 6).value = order.get("delivery_date", "") or ""

        price_kwr = order.get("calculated_price_kwr", "") or ""
        ws.cell(row, 7).value = price_kwr
        if price_kwr:
            ws.cell(row, 7).number_format = '#,##0'

        if qty and price_kwr:
            ws.cell(row, 8).value = f"=G{row}*E{row}"
            ws.cell(row, 8).number_format = '#,##0'

    # 更新 TOTAL 行
    last_data_row = actual_total_row - 1
    ws.cell(actual_total_row, 1).value = "Total Amount:"
    ws.cell(actual_total_row, 8).value = f"=SUM(H{first_data_row}:H{last_data_row})"
    ws.cell(actual_total_row, 8).number_format = '#,##0'

    try:
        ws.merge_cells(f"A{actual_total_row}:G{actual_total_row}")
    except:
        pass

    ws.print_area = f"$A$1:$H${ws.max_row}"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    wb.save(output_path)

    return True, {
        "excel_path": output_path,
        "invoice_no": now.strftime("UNI%Y%m%d%H"),
        "cli_name": first_order.get("cli_name", ""),
        "count": data_count
    }


# ============================================================
# 韩文报价单生成 (견적서)
# ============================================================

def generate_koquote(offer_ids, output_base=None, template_dir=None):
    """
    生成韩文报价单 (견적서)

    Args:
        offer_ids: 报价ID列表
        output_base: 输出基础目录（可选）
        template_dir: 模板目录（可选）

    Returns:
        tuple: (success: bool, result: dict or error_message: str)
    """
    if openpyxl is None:
        return False, "缺少依赖: 请安装 openpyxl -> pip install openpyxl"

    if not offer_ids:
        return False, "未提供报价编号"

    offers = get_offers_for_document(offer_ids)
    if not offers:
        return False, f"报价编号 {offer_ids} 不存在"

    cli_names = set(o.get("cli_name") or "未知客户" for o in offers)
    if len(cli_names) > 1:
        return False, f"报价属于不同客户 ({', '.join(cli_names)})，无法生成同一份报价单"

    cli_name = list(cli_names)[0]

    # 确定输出目录
    project_root = os.environ.get('UNIULTRA_PROJECT_ROOT',
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if not output_base:
        output_base = os.environ.get('UNIULTRA_OUTPUT_DIR')
    if not output_base:
        output_base = os.path.join(project_root, "Trans")

    if not template_dir:
        template_dir = os.path.join(project_root, "templates", "koquote")

    now = datetime.now()
    date_dir = now.strftime("%Y%m%d")
    time_str = now.strftime("%Y%m%d%H%M")

    output_dir = os.path.join(output_base, cli_name, date_dir)
    output_filename = f"유니콘_전자부품견적서_{time_str}.xlsx"
    output_path = os.path.join(output_dir, output_filename)

    # 获取汇率
    krw_val, _ = get_exchange_rates()

    return _generate_koquote_excel(offers, template_dir, output_path, krw_val)


def _generate_koquote_excel(offers, template_dir, output_path, exchange_rate_krw):
    """生成韩文报价单 Excel 文件"""
    data_count = len(offers)
    first_offer = offers[0]
    now = datetime.now()

    # 查找模板文件
    template_path = None
    if os.path.isdir(template_dir):
        for f in os.listdir(template_dir):
            if f.endswith(".xlsx") and not f.startswith("~"):
                template_path = os.path.join(template_dir, f)
                break

    if not template_path or not os.path.exists(template_path):
        return False, f"模板文件不存在于 {template_dir}"

    wb = openpyxl.load_workbook(template_path)
    ws = wb.active

    # 填写头部信息 (根据SKILL.md的模板结构)
    # C5 = 客户公司全名
    cli_full_name = first_offer.get("cli_full_name", "") or first_offer.get("cli_name", "")
    ws['C5'] = cli_full_name

    # 编号和日期
    quote_no = now.strftime("%Y%m%d%H%M")
    ws['D6'] = f"제 {quote_no}호"
    ws['D7'] = f"{now.year}년 {now.month}월 {now.day}일"

    # 数据行处理 (假设数据从第15行开始，根据模板调整)
    first_data_row = 15
    template_data_rows = 1

    # 调整行数
    rows_diff = data_count - template_data_rows
    if rows_diff > 0:
        ws.insert_rows(first_data_row + template_data_rows, rows_diff)

    # 写入数据
    total_qty = 0
    total_amount = 0

    for idx, offer in enumerate(offers):
        row = first_data_row + idx

        # No.
        ws.cell(row=row, column=1).value = idx + 1

        # 모델명 (型号)
        ws.cell(row=row, column=2).value = offer.get("inquiry_mpn", "") or ""

        # 제공가능한 부품 (报价型号)
        ws.cell(row=row, column=3).value = offer.get("quoted_mpn", "") or offer.get("inquiry_mpn", "") or ""

        # 메이커 (品牌)
        ws.cell(row=row, column=4).value = offer.get("inquiry_brand", "") or ""

        # 생산일자 (批次号)
        ws.cell(row=row, column=5).value = offer.get("date_code", "") or ""

        # 수량(EA) (数量)
        qty = offer.get("quoted_qty") or offer.get("inquiry_qty") or 0
        try:
            qty = int(qty)
        except:
            qty = 0
        ws.cell(row=row, column=6).value = qty
        ws.cell(row=row, column=6).number_format = '#,##0'
        total_qty += qty

        # 단가(KRW) (单价)
        price_kwr = offer.get("offer_price_rmb")
        if price_kwr and float(price_kwr or 0) > 0:
            price_kwr = round(float(price_kwr) * exchange_rate_krw, 1)
        else:
            price_kwr = 0
        ws.cell(row=row, column=7).value = price_kwr
        ws.cell(row=row, column=7).number_format = '#,##0'

        # 납기 (交期)
        ws.cell(row=row, column=8).value = offer.get("delivery_date", "") or ""

        # 비고 (备注)
        ws.cell(row=row, column=9).value = offer.get("remark", "") or ""

        total_amount += price_kwr * qty

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    wb.save(output_path)

    return True, {
        "excel_path": output_path,
        "quote_no": quote_no,
        "cli_name": first_offer.get("cli_name", ""),
        "count": data_count,
        "total_qty": total_qty,
        "total_amount": total_amount
    }