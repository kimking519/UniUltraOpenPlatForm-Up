#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Excel to PDF Converter for PI Generator
将 PI Excel 文件转换为 PDF 格式

创建时间: 2026-03-08
功能: 将生成的 PI Excel 文件转换为 PDF，用于发送给客户
依赖: LibreOffice (Windows/WSL)
"""

import os
import platform
import subprocess
import shutil
from pathlib import Path


def is_wsl():
    """检测是否在 WSL 环境中运行"""
    if platform.system() == "Linux":
        try:
            with open("/proc/version", "r") as f:
                version = f.read().lower()
                return "microsoft" in version or "wsl" in version
        except:
            pass
    return False


def find_libreoffice(config=None):
    """
    查找 LibreOffice 可执行文件路径
    优先级: 配置文件 > 环境变量 > 系统PATH
    """
    # 1. 检查配置文件
    if config:
        if not is_wsl():
            config_path = config.get("libreoffice_path_windows")
            if config_path and Path(config_path).exists():
                return config_path
        else:
            config_path = config.get("libreoffice_path_wsl")
            if config_path and Path(config_path).exists():
                return config_path

    # 2. 检查环境变量
    env_path = os.environ.get("LIBREOFFICE_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    # 3. 在系统 PATH 中查找
    if is_wsl():
        possible_paths = [
            "/usr/bin/libreoffice",
            "/usr/bin/soffice",
            "/snap/bin/libreoffice",
        ]
    else:
        possible_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]

    for path in possible_paths:
        if Path(path).exists():
            return path

    return None


def convert_to_pdf(xlsx_path, config=None):
    """
    将 Excel 文件转换为 PDF

    Args:
        xlsx_path: Excel 文件路径
        config: 配置字典（可选）

    Returns:
        tuple: (成功标志, PDF路径或错误信息)
    """
    xlsx_path = Path(xlsx_path)
    if not xlsx_path.exists():
        return False, f"Excel 文件不存在: {xlsx_path}"

    # 查找 LibreOffice
    libreoffice_path = find_libreoffice(config)
    if not libreoffice_path:
        error_msg = "LibreOffice 未安装。请安装后重试。\n"
        if is_wsl():
            error_msg += "  WSL: sudo apt install libreoffice"
        else:
            error_msg += "  Windows: https://www.libreoffice.org/download/"
        return False, error_msg

    # PDF 输出路径
    pdf_path = xlsx_path.with_suffix('.pdf')

    try:
        output_dir = str(xlsx_path.parent)

        cmd = [
            libreoffice_path,
            "--headless",
            "--convert-to", "pdf",
            "--outdir", output_dir,
            str(xlsx_path)
        ]

        # 执行转换
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120  # 2分钟超时
        )

        # 检查输出文件
        if pdf_path.exists():
            return True, str(pdf_path)
        else:
            return False, f"转换失败: {result.stderr or '未知错误'}"

    except subprocess.TimeoutExpired:
        return False, "转换超时（超过2分钟）"
    except Exception as e:
        return False, str(e)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PI Excel 转 PDF 工具")
    parser.add_argument("--input", "-i", required=True, help="Excel 文件路径")
    args = parser.parse_args()

    success, result = convert_to_pdf(args.input)

    if success:
        print(f"[OK] PDF 生成成功！")
        print(f"     文件路径: {result}")
    else:
        print(f"[FAIL] 转换失败: {result}")