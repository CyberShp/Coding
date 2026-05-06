# 数据库升级攻略

## 概述

Observation Web 使用 **「新建数据库 + 数据迁移」** 方式升级，不再依赖增量 ALTER 迁移脚本。

### 核心流程

```
升级时（若 observation_web.db 已存在）:
1. 用 ORM 模型创建新库 observation_web.db.migrate_new
2. ATTACH 旧库，按列交集逐表拷贝数据
3. 原子替换：mv 新库 → observation_web.db
```

### 优势

- **ORM 即真理**：改 `backend/models/*.py` 即可，无需写迁移脚本
- **无 SQLite 限制**：不受 DROP COLUMN、ALTER COLUMN 不支持影响
- **回滚简单**：旧 .db 在 `backups/` 中，直接恢复即可

---

## 升级方式

### 1. 使用 upgrade.sh（推荐）

```bash
./scripts/upgrade.sh <升级包.tar.gz>
```

脚本会：

1. 备份到 `backups/backup_YYYYMMDD_HHMMSS/`
2. 停止服务
3. 解压并替换代码
4. 安装依赖
5. **执行数据库升级**（`migrate_if_needed` → `create_tables`）
6. 启动服务
7. 健康检查

### 2. 手动升级

```bash
# 1. 停止服务
pkill -f "uvicorn.*backend.main"

# 2. 备份数据库
cp observation_web.db observation_web.db.bak

# 3. 执行迁移（需在项目根目录）
cd /path/to/observation_web
python3 -c "
from backend.db.schema_migrate import migrate_if_needed
from backend.db.database import init_db
import asyncio
from backend.db.database import create_tables

migrate_if_needed()  # 若有旧库则迁移
init_db()
asyncio.run(create_tables())
"

# 4. 启动服务
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8001
```

---

## 开发者：修改 Schema 时

### 只需改 ORM 模型

1. 编辑 `backend/models/*.py`（新增/删除/修改列）
2. 下次升级时，`migrate_if_needed` 会自动：
   - 用最新 ORM 建新库
   - 按列名交集拷贝旧数据
   - 替换旧库

### 列变更说明

| 操作       | 行为说明 |
|------------|----------|
| 新增列     | 新库有该列，旧数据拷贝时该列为 NULL/默认值 |
| 删除列     | 新库无该列，拷贝时自动忽略，旧数据该列丢失 |
| 重命名列   | 视为「删旧列 + 增新列」，需在迁移前确保数据已处理或接受丢失 |
| 修改类型   | 新库用新类型，拷贝时 SQLite 会尝试转换，不兼容可能报错 |

### 新增表

- 在 `backend/models/` 新增模型并 `__tablename__`
- 在 `database.create_tables` 的 import 中加入新模型
- 在 `schema_migrate.TABLE_ORDER` 中按 FK 顺序加入表名

---

## 回滚

### 使用 upgrade.sh 回滚

```bash
./scripts/upgrade.sh --rollback
```

会恢复到最近一次 `backups/backup_*` 中的代码和数据库。

### 手动回滚

```bash
# 停止服务
pkill -f "uvicorn.*backend.main"

# 恢复备份的数据库
cp backups/backup_YYYYMMDD_HHMMSS/observation_web.db ./

# 启动服务
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8001
```

---

## 故障排查

### 迁移失败

- 查看日志中的 `Schema migration failed` 及堆栈
- 旧库未被修改，可直接重试或从备份恢复
- 若为列类型不兼容，需在 ORM 中调整类型或写一次性数据转换脚本

### 健康检查失败

```bash
./scripts/upgrade.sh --rollback
```

回滚后检查日志，确认配置与依赖无误再重新升级。

### 数据库被占用

迁移前需确保无进程持有数据库连接。`upgrade.sh` 会先 `pkill` 并 `sleep 2`，若仍有占用，可手动停止相关进程后再执行迁移。

---

## 技术细节

- **实现**：`backend/db/schema_migrate.py`
- **表顺序**：`TABLE_ORDER` 按外键依赖排序，迁移时 `PRAGMA foreign_keys=OFF` 可放宽顺序要求
- **列交集**：`PRAGMA table_info` 取新旧表列名，只拷贝共有列
- **原子替换**：`os.replace(new_path, db_path)` 保证替换原子性
