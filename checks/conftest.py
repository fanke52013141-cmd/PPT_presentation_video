"""把测试套件与真实项目数据库隔离。

背景
----
``checks/`` 下的测试直接使用 ``database.SessionLocal``（例如 agent e2e、
契约 parity、video 与项目相关用例），因此**每跑一次 pytest 都会往用户的真实
``data/projects.db`` 与 ``runs/`` 里写入一批测试项目** —— 实测一轮全量测试
会新增约 15-30 个项目（``Agent E2E Test Project``、``Lock Test``、
``Parity Mask Default Test`` 等固定名称），污染项目列表、产物记录和运行目录。

做法
----
在任何测试模块导入 ``database`` 之前，把数据库指向本次会话专属的临时文件：

- 通过 ``PPT_STUDIO_DB_PATH`` 覆盖（``database.py`` 支持该变量）；
- 若调用方已经显式设置它（例如 CI 或 ``scripts/run_checks.py`` 自行指定），
  则尊重原值，不覆盖；
- 初始化 schema、默认设置与默认账号（迁移 0012 会插入 ``default`` 账号），
  使测试看到的结构与真实库一致，按账号过滤的接口不会因此 404。

临时目录带 ``ignore_cleanup_errors``：SQLite 连接可能持有文件句柄，
清理失败不应在测试输出里制造噪音。
"""

from __future__ import annotations

import os
import tempfile

_TEMP_DIRECTORY: tempfile.TemporaryDirectory | None = None

if not os.environ.get("PPT_STUDIO_DB_PATH") or not os.environ.get("PPT_STUDIO_RUNS_DIR"):
    _TEMP_DIRECTORY = tempfile.TemporaryDirectory(
        prefix="pptstudio-tests-",
        ignore_cleanup_errors=True,
    )

# 数据库：测试不再写入用户真实的 data/projects.db
if not os.environ.get("PPT_STUDIO_DB_PATH"):
    os.environ["PPT_STUDIO_DB_PATH"] = os.path.join(_TEMP_DIRECTORY.name, "projects.db")

# 运行产物目录：测试创建的项目不再落在真实的 runs/ 下。
# 未隔离时，只走 session 级夹具的用例（agent e2e、契约 parity 等）会在
# 真实 runs/ 里留下无数据库记录的孤儿目录。
if not os.environ.get("PPT_STUDIO_RUNS_DIR"):
    os.environ["PPT_STUDIO_RUNS_DIR"] = os.path.join(_TEMP_DIRECTORY.name, "runs")

import database  # noqa: E402  （必须在设置环境变量之后导入）

# 建立与真实库一致的结构：schema + 默认设置 + 默认账号。
database.init_db()
