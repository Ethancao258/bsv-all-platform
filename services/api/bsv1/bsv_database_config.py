"""BSV1 数据库位置的唯一配置入口（V2.3.1，本地验收）。

后续其他 Python 程序读取同一数据库位置：
    from bsv_database_config import get_database_path
    print(get_database_path())

注意：本配置只决定 SQLite 文件路径，不负责联网同步。多设备应该通过 BSV1 后端 API
读写，不要把 SQLite 数据文件挂到多个设备上直接并发修改。
"""
from __future__ import annotations
import os
from pathlib import Path

# ============== 你只需要修改下方这一行 ==============
# 默认：程序目录下 data 文件夹中的现有数据库（保持与 V2.3 兼容）。
# 例如 Windows：DATABASE_FILE = r"D:\BSV1\data\bsv1_orders.sqlite3"
# 例如同级其他目录：DATABASE_FILE = r"..\BSV_ALL\database\bsv1.sqlite3"
# 路径中的文件名可以自行修改。相对路径始终按本程序所在目录解析。
DATABASE_FILE = r"data/bsvm_seatdesk.sqlite3"
# ====================================================

# 安全开关：如果你已经在默认位置有数据库，换成一个不存在的新路径时，
# 会默认阻止启动，以免误以为旧订单消失。确实要创建全新库时可改为 True。
ALLOW_NEW_EMPTY_DB_WHEN_OLD_EXISTS = False

# 在云端 / 自动化部署时，环境变量 BSV_DB_PATH 的优先级高于上面的配置。
# 本地 Windows 双击启动通常不设置该变量，因此直接读取 DATABASE_FILE。
ENVIRONMENT_VARIABLE = "BSV_DB_PATH"


def get_database_path(root: Path | None = None) -> Path:
    app_root = Path(root) if root is not None else Path(__file__).resolve().parent
    app_root = app_root.resolve()
    selected = (os.environ.get(ENVIRONMENT_VARIABLE) or DATABASE_FILE).strip()
    if not selected:
        raise RuntimeError('数据库路径配置为空：请修改 bsv_database_config.py 中的 DATABASE_FILE。')
    if selected.lower() == ':memory:':
        raise RuntimeError('禁止使用内存数据库，避免关闭程序后订单丢失。')
    path = Path(os.path.expandvars(os.path.expanduser(selected)))
    if not path.is_absolute():
        path = app_root / path
    path = path.resolve()
    if path.exists() and not path.is_file():
        raise RuntimeError('数据库配置指向的不是文件：' + str(path))
    if not path.suffix.lower() in ('.sqlite3', '.sqlite', '.db'):
        raise RuntimeError('数据库文件名请以 .sqlite3、.sqlite 或 .db 结尾。')
    default = (app_root / 'data' / 'bsvm_seatdesk.sqlite3').resolve()
    if (path != default and not path.exists() and default.is_file()
            and not ALLOW_NEW_EMPTY_DB_WHEN_OLD_EXISTS):
        raise RuntimeError(
            '检测到默认位置已有旧数据库，但新配置的路径不存在：' + str(path) + '\n'
            '为了避免误创建空库，已阻止启动。请先用“导入旧版SQLite.py”复制旧库，'
            '或在确实需要全新数据库时设置 ALLOW_NEW_EMPTY_DB_WHEN_OLD_EXISTS = True。'
        )
    return path
