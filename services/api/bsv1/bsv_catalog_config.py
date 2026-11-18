"""BSV ALL V9 Excel 来源配置。只改变路径，不修改工作簿原文。

优先级：环境变量 BSV_V9_XLSX > EXCEL_SOURCE_FILE。
相对路径按本程序目录解析。商品和订单使用各自的稳定ID，不使用会随分类变化的SKU当外键。
"""
from pathlib import Path
import os
EXCEL_SOURCE_FILE = r"resources/BSV_ALL_V9.xlsx"
ENV_NAME = "BSV_V9_XLSX"
# 本地演练使用的原V2.3.1示例商品仍可操作；这些商品不能用于正式收款。
SHOW_LOCAL_TRAINING_ITEMS = True

def get_excel_path(root=None):
    root = Path(root or Path(__file__).resolve().parent).resolve()
    raw=(os.environ.get(ENV_NAME) or EXCEL_SOURCE_FILE).strip()
    if not raw:
        raise ValueError('未配置V9 Excel文件位置')
    p=Path(os.path.expandvars(os.path.expanduser(raw)))
    if not p.is_absolute():p=root/p
    p=p.resolve()
    if p.suffix.lower()!='.xlsx':raise ValueError('数据源必须是.xlsx文件')
    if not p.is_file():raise FileNotFoundError('找不到V9 Excel数据源：'+str(p))
    return p
