# Windows 本地目录 -> 多服务器 SFTP 自动同步工具开发规格（AI 编程版）

- 文档类型：实施规格 / 直接用于 AI 编程工具
- 目标平台：Windows 客户端，Linux SFTP 服务器
- 开发语言：Python 3.12+
- 首版范围：V1
- 输出目标：可打包的桌面应用，支持 GUI 配置、多服务器、多目录映射、自动监听上传、配置持久化

---

## 1. 目标

实现一个 Windows 桌面程序，持续监听多个本地目录，把文件变更自动上传到对应的远程 SFTP 目录。

### 1.1 必须支持

1. 多个 SFTP 服务器配置
2. 多个本地目录 -> 远程目录映射
3. 不同映射可指向不同服务器
4. SFTP 基础能力
   - host
   - port
   - username
   - password
   - private key
   - private key passphrase
   - connect timeout
   - host key 持久化
5. GUI 管理
   - 服务器 CRUD
   - 映射 CRUD
   - 启停同步
   - 测试连接
   - 日志查看
6. 配置持久化
7. 自动监听并上传文件新增 / 修改
8. 启动补扫，修复应用关闭期间漏掉的变更
9. 失败重试
10. 远程删除默认关闭，可按映射开启

### 1.2 明确不做

1. 不做双向同步
2. 不做 Git 集成
3. 不做 rsync 协议
4. 不做块级增量传输
5. 不做实时远端目录扫描对比
6. 不做权限 / owner / group 同步
7. 不做符号链接同步
8. 不做 Linux/macOS 客户端版本
9. 不做分布式或服务端 agent

---

## 2. 固定技术决策

## 2.1 依赖

```txt
paramiko   # SSH / SFTP
watchdog   # 本地目录监听
PySide6    # GUI
sqlite3    # 配置与状态持久化（标准库）
keyring    # 密码/口令存系统密钥库
logging    # 日志（标准库）
pathlib    # 路径处理（标准库）
queue      # 任务队列（标准库）
threading  # 后台线程（标准库）
```

## 2.2 关键决策

1. 不使用 asyncio。采用“同步 IO + 后台线程”。
2. GUI 主线程只处理界面，禁止做网络 IO、目录扫描、SFTP 上传。
3. 每个服务器一个独立 worker 线程和一个独立任务队列。
4. watchdog 只产生日志化后的原始事件，不直接上传。
5. 所有原始事件先进入聚合器，做去重、防抖、事件合并，再生成最终任务。
6. SQLite 只存配置、状态、历史；密码和私钥口令存 keyring。
7. 远程上传采用“临时文件上传 -> 原子重命名”。
8. 启动时执行补扫，不依赖 watchdog 覆盖应用关闭期间的改动。
9. 远程路径统一按 POSIX 路径处理。
10. 默认不开启远程删除。
11. V1 只同步文件，不同步空目录，不同步符号链接，不同步权限。

---

## 3. 运行目录与持久化布局

使用 `%APPDATA%/SFTPAutoSync/` 作为应用数据根目录。

```txt
%APPDATA%/SFTPAutoSync/
├─ app.db
├─ known_hosts
├─ logs/
│  ├─ app.log
│  └─ error.log
└─ cache/
   └─ optional_runtime_files
```

说明：

- `app.db`：SQLite 数据库
- `known_hosts`：Paramiko 使用的主机密钥文件
- `logs/`：滚动日志
- secrets 不写入 `app.db`，统一走 `keyring`

---

## 4. 总体架构

## 4.1 进程模型

单进程桌面应用，包含以下线程：

1. Qt GUI 主线程
2. watchdog observer 线程（watchdog 内部）
3. event aggregator 线程
4. startup rescan 线程
5. 每个服务器 1 个 sync worker 线程
6. 可选：日志转发线程（不是必须）

## 4.2 架构图

```txt
GUI(Main Thread)
   |
   +-- Config Service
   +-- Mapping Service
   +-- Server Service
   +-- UI State Store
   |
   +-- Sync Engine -----------------------------+
         |                                      |
         +-- Watchdog Event Handler             |
         |        -> raw_event_queue            |
         |                                      |
         +-- Event Aggregator Thread            |
         |        -> per_server_task_queue      |
         |                                      |
         +-- Startup Rescan Thread              |
         |        -> per_server_task_queue      |
         |                                      |
         +-- Server Worker A -> Paramiko SSH/SFTP
         +-- Server Worker B -> Paramiko SSH/SFTP
         +-- Server Worker N -> Paramiko SSH/SFTP
```

## 4.3 数据流

1. GUI 加载配置
2. SyncEngine 根据 enabled mappings 启动 watchdog
3. watchdog 产生原始文件事件
4. EventAggregator 规范化事件，按 `(mapping_id, relative_path)` 去重
5. 生成最终 `SyncTask`
6. Dispatcher 按 `server_id` 投递到对应 worker 队列
7. Worker 建立或复用 SFTP 连接
8. 执行上传 / 删除
9. 写入 `sync_state` 和 `sync_history`
10. 通过 Qt signal 更新 GUI 状态

---

## 5. 目录结构（必须按此拆分）

```txt
sftp_auto_sync/
├─ app/
│  ├─ main.py
│  ├─ bootstrap.py
│  ├─ app_paths.py
│  ├─ constants.py
│  └─ signals.py
├─ domain/
│  ├─ enums.py
│  ├─ models.py
│  ├─ dto.py
│  └─ errors.py
├─ infra/
│  ├─ db/
│  │  ├─ connection_factory.py
│  │  ├─ schema.sql
│  │  ├─ migration_runner.py
│  │  ├─ server_repo.py
│  │  ├─ mapping_repo.py
│  │  ├─ state_repo.py
│  │  ├─ history_repo.py
│  │  └─ settings_repo.py
│  ├─ secrets/
│  │  └─ secret_store.py
│  ├─ sftp/
│  │  ├─ host_keys.py
│  │  ├─ connection_manager.py
│  │  ├─ path_mapper.py
│  │  ├─ remote_ops.py
│  │  └─ uploader.py
│  ├─ watcher/
│  │  ├─ observer_manager.py
│  │  └─ event_handler.py
│  └─ logging/
│     └─ log_setup.py
├─ services/
│  ├─ validation_service.py
│  ├─ server_service.py
│  ├─ mapping_service.py
│  ├─ startup_rescan_service.py
│  ├─ event_aggregator.py
│  ├─ sync_engine.py
│  └─ dispatcher.py
├─ workers/
│  └─ server_worker.py
├─ ui/
│  ├─ main_window.py
│  ├─ pages/
│  │  ├─ dashboard_page.py
│  │  ├─ servers_page.py
│  │  ├─ mappings_page.py
│  │  ├─ logs_page.py
│  │  └─ settings_page.py
│  ├─ dialogs/
│  │  ├─ server_dialog.py
│  │  ├─ mapping_dialog.py
│  │  └─ test_connection_dialog.py
│  └─ viewmodels/
│     ├─ server_vm.py
│     ├─ mapping_vm.py
│     ├─ dashboard_vm.py
│     └─ log_vm.py
├─ tests/
│  ├─ test_validation.py
│  ├─ test_path_mapper.py
│  ├─ test_event_aggregator.py
│  ├─ test_uploader.py
│  ├─ test_startup_rescan.py
│  └─ test_repo.py
├─ requirements.txt
└─ README.md
```

---

## 6. 核心数据模型

## 6.1 枚举

```python
class AuthType(str, Enum):
    PASSWORD = "password"
    PRIVATE_KEY = "private_key"

class HostKeyPolicy(str, Enum):
    STRICT = "strict"
    TOFU = "tofu"  # trust on first use

class DeletePolicy(str, Enum):
    IGNORE = "ignore"
    DELETE_FILE = "delete_file"

class TaskAction(str, Enum):
    UPSERT = "upsert"   # create/modify/move-dst
    DELETE = "delete"

class SyncStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"

class MappingRunState(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"
```

## 6.2 模型

```python
@dataclass(slots=True)
class ServerProfile:
    id: int | None
    name: str
    host: str
    port: int
    username: str
    auth_type: AuthType
    password_ref: str | None
    private_key_path: str | None
    private_key_passphrase_ref: str | None
    connect_timeout_sec: int
    host_key_policy: HostKeyPolicy
    enabled: bool
    created_at: str | None
    updated_at: str | None

@dataclass(slots=True)
class SyncMapping:
    id: int | None
    name: str
    server_id: int
    local_dir: str
    remote_dir: str
    recursive: bool
    enabled: bool
    delete_policy: DeletePolicy
    startup_rescan: bool
    ignore_patterns: list[str]
    note: str | None
    created_at: str | None
    updated_at: str | None

@dataclass(slots=True)
class SyncTask:
    task_id: str
    mapping_id: int
    server_id: int
    action: TaskAction
    local_path: str | None
    relative_path: str
    remote_path: str
    source: str           # live_event / startup_rescan / retry
    priority: int         # 0 live, 10 rescan, 20 retry
    retry_count: int
    enqueue_ts: float

@dataclass(slots=True)
class FileSnapshot:
    size: int
    mtime_ns: int

@dataclass(slots=True)
class SyncStateRecord:
    mapping_id: int
    relative_path: str
    last_local_size: int | None
    last_local_mtime_ns: int | None
    last_uploaded_at: str | None
    last_status: str | None
    last_error: str | None
    remote_path: str

@dataclass(slots=True)
class AppSetting:
    key: str
    value: str
```

---

## 7. SQLite 设计

## 7.1 数据库约束

1. 打开 WAL 模式
2. 打开 foreign_keys
3. 不共享 SQLite connection 到多个线程
4. 每个线程通过 `connection_factory` 获取独立连接
5. 所有写操作必须显式事务
6. `sync_history` 允许定期裁剪

## 7.2 schema.sql

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS server_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 22,
    username TEXT NOT NULL,
    auth_type TEXT NOT NULL CHECK (auth_type IN ('password', 'private_key')),
    password_ref TEXT,
    private_key_path TEXT,
    private_key_passphrase_ref TEXT,
    connect_timeout_sec INTEGER NOT NULL DEFAULT 10,
    host_key_policy TEXT NOT NULL DEFAULT 'tofu'
        CHECK (host_key_policy IN ('strict', 'tofu')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    server_id INTEGER NOT NULL,
    local_dir TEXT NOT NULL,
    remote_dir TEXT NOT NULL,
    recursive INTEGER NOT NULL DEFAULT 1 CHECK (recursive IN (0, 1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    delete_policy TEXT NOT NULL DEFAULT 'ignore'
        CHECK (delete_policy IN ('ignore', 'delete_file')),
    startup_rescan INTEGER NOT NULL DEFAULT 1 CHECK (startup_rescan IN (0, 1)),
    ignore_patterns_json TEXT NOT NULL DEFAULT '[]',
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(server_id) REFERENCES server_profiles(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mapping_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    last_local_size INTEGER,
    last_local_mtime_ns INTEGER,
    last_uploaded_at TEXT,
    last_status TEXT,
    last_error TEXT,
    remote_path TEXT NOT NULL,
    UNIQUE(mapping_id, relative_path),
    FOREIGN KEY(mapping_id) REFERENCES sync_mappings(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mapping_id INTEGER,
    server_id INTEGER,
    action TEXT NOT NULL,
    relative_path TEXT,
    remote_path TEXT,
    status TEXT NOT NULL,
    message TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(mapping_id) REFERENCES sync_mappings(id) ON DELETE SET NULL,
    FOREIGN KEY(server_id) REFERENCES server_profiles(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mapping_server_id
    ON sync_mappings(server_id);

CREATE INDEX IF NOT EXISTS idx_state_mapping_path
    ON sync_state(mapping_id, relative_path);

CREATE INDEX IF NOT EXISTS idx_history_created_at
    ON sync_history(created_at);

CREATE INDEX IF NOT EXISTS idx_history_mapping_id
    ON sync_history(mapping_id);
```

## 7.3 keyring 设计

不在 SQLite 中存储明文密码。

key 名约定：

```txt
service = "sftp-auto-sync"
username = "server:{server_id}:password"
username = "server:{server_id}:key_passphrase"
```

也可在 server 创建前先用临时 UUID，保存后再重命名引用。实现层可封装，不要散落在 UI 代码里。

---

## 8. 配置校验规则

## 8.1 ServerProfile 校验

1. `name` 非空，唯一
2. `host` 非空
3. `port` 范围 `1..65535`
4. `username` 非空
5. `auth_type=password` 时必须有密码
6. `auth_type=private_key` 时 `private_key_path` 必须存在且可读
7. `connect_timeout_sec >= 3`
8. `host_key_policy` 仅允许 `strict` 或 `tofu`

## 8.2 SyncMapping 校验

1. `name` 非空，唯一
2. `server_id` 必须存在
3. `local_dir` 必须为绝对路径，必须存在，必须是目录
4. `remote_dir` 必须为 POSIX 绝对路径，以 `/` 开头
5. `ignore_patterns` 必须是字符串数组
6. 不允许 enabled mapping 之间出现本地目录重叠
   - A 是 B 的父目录 -> 拒绝
   - A 和 B 完全相同 -> 拒绝
7. `delete_policy` 只允许 `ignore` 或 `delete_file`

说明：禁止重叠映射，避免同一文件被多个 mapping 重复处理。

---

## 9. 路径规则

## 9.1 本地路径规范化

统一使用：

```python
Path(local_path).resolve()
```

比较时再叠加：

```python
os.path.normcase(str(path))
```

用于 Windows 不区分大小写的比较。

## 9.2 relative_path 规则

- 相对路径一律基于 `mapping.local_dir`
- 存库时统一转成 POSIX 风格
- 例：
  - local root: `D:\www\project`
  - file: `D:\www\project\static\app.js`
  - relative_path: `static/app.js`

## 9.3 remote_path 规则

```python
remote_path = PurePosixPath(mapping.remote_dir) / PurePosixPath(relative_path)
```

示例：

```txt
remote_dir   = /var/www/project
relative_path = static/app.js
remote_path   = /var/www/project/static/app.js
```

## 9.4 ignore 匹配规则

ignore pattern 采用更易理解的简化写法：

1. 普通规则默认匹配文件名（basename）
   - 例如：`db*` 忽略所有以 `db` 开头的文件
   - 例如：`*.dat` 忽略所有 `.dat` 文件
2. 以 `/` 结尾表示目录规则
   - 例如：`data/` 忽略名为 `data` 的目录及其全部内容
   - 目录规则按路径分段精确匹配，不应误伤 `database/` 之类名称
3. 如规则本身包含 `/` 且不是目录规则，可按相对路径（POSIX）匹配
4. 命中任意一条规则即忽略

推荐默认 ignore：

```python
DEFAULT_IGNORE_PATTERNS = [
    ".git/",
    ".idea/",
    ".vscode/",
    ".DS_Store",
    "Thumbs.db",
    "*.swp",
    "*.tmp",
    "*~",
]
```

V1 不默认忽略 `node_modules`、`dist`、`build`，由用户自行配置。

---

## 10. 事件模型与聚合规则

## 10.1 watchdog 原始事件到内部事件映射

### 文件事件

| watchdog 事件 | 内部动作 |
|---|---|
| file created | UPSERT |
| file modified | UPSERT |
| file moved(src) | DELETE（仅 delete_policy=delete_file 时） |
| file moved(dest) | UPSERT |
| file deleted | DELETE（仅 delete_policy=delete_file 时） |

### 目录事件

- 目录 created / modified / moved / deleted 默认不直接生成任务
- 远程目录在上传文件时按需递归创建
- 空目录不同步

## 10.2 聚合键

```txt
dedupe_key = (mapping_id, relative_path)
```

## 10.3 聚合规则

1. 同一 `dedupe_key` 在 debounce 窗口内只保留最后一个动作
2. `UPSERT` 覆盖之前的 `UPSERT`
3. `UPSERT` 覆盖之前的 `DELETE`
4. `DELETE` 覆盖之前的 `UPSERT`
5. 移动事件拆成两条：
   - old path -> DELETE（取决于 delete_policy）
   - new path -> UPSERT
6. 目录事件不入最终任务队列
7. disabled mapping 不生成任务
8. ignore 命中则直接丢弃

## 10.4 debounce 参数

固定参数：

```txt
DEBOUNCE_MS = 800
AGGREGATOR_TICK_MS = 200
```

说明：800ms 对编辑器频繁保存、前端编译短时间多次写入比较稳。

---

## 11. 文件稳定性检查

上传前必须检查文件是否已经写完，避免上传半文件。

## 11.1 规则

对 `UPSERT` 任务执行：

1. 若文件不存在，任务记为 `SKIPPED`
2. 若是目录，直接跳过
3. 若是符号链接，直接跳过
4. 连续两次读取 `stat().st_size` 和 `stat().st_mtime_ns`
5. 间隔 `STABILITY_CHECK_INTERVAL_MS = 300`
6. 若两次结果一致，认为文件稳定
7. 若最多 `STABILITY_MAX_CHECKS = 5` 次仍不稳定，任务延迟重试

## 11.2 重试策略

```txt
max_retries = 5
retry_delay_seconds = [1, 2, 5, 10, 20]
```

超过最大次数后标记失败，写日志和历史。

---

## 12. 上传与删除协议

## 12.1 远程目录创建

上传前，递归确保远程父目录存在。

必须实现：

```python
ensure_remote_dir(remote_dir: str) -> None
```

要求：

- 逐级 `stat`
- 不存在则 `mkdir`
- 已存在则跳过
- 缓存已确认存在的目录，减少重复 SFTP 请求

## 12.2 上传协议

禁止直接覆盖正式文件。采用：

1. 生成临时文件路径  
   `remote_tmp = remote_path + ".__uploading__"`
2. 上传到 `remote_tmp`
3. 可选：校验远程 size 是否等于本地 size
4. 原子 rename `remote_tmp -> remote_path`
5. 更新 `sync_state`
6. 写 `sync_history`

说明：使用 Paramiko 时优先调用支持覆盖的 rename 方案；若目标服务器不支持扩展，再退化为兼容方案。

## 12.3 删除协议

仅在 mapping.delete_policy == `delete_file` 时执行。

规则：

1. 只删除文件，不递归删除目录
2. 远程文件不存在则视为成功
3. 删除成功后从 `sync_state` 删除该记录
4. 写 `sync_history`

---

## 13. 启动补扫（必须实现）

## 13.1 目标

应用关闭期间发生的本地变化，watchdog 无法捕获。启动补扫负责恢复。

## 13.2 算法

对每个 `enabled and startup_rescan=true` 的 mapping：

1. 遍历本地目录下所有文件
2. 跳过 ignore 命中的文件
3. 跳过目录和符号链接
4. 计算 `relative_path`
5. 读取当前 `size` + `mtime_ns`
6. 查 `sync_state`：
   - 无记录 -> 生成 `UPSERT`
   - 有记录且 `(size, mtime_ns)` 不同 -> 生成 `UPSERT`
   - 有记录且相同 -> 跳过
7. 若 delete_policy=`delete_file`，可选执行“反向删除补扫”
   - 查 `sync_state` 里存在但本地已不存在的 relative_path
   - 生成 `DELETE`
   - V1 建议开启
8. 补扫任务优先级低于实时事件

## 13.3 补扫优先级

```txt
live event priority = 0
startup rescan priority = 10
retry priority = 20
```

worker 使用 `PriorityQueue`。

---

## 14. 连接管理

## 14.1 规则

每个 `server_id` 维护一个 `ServerWorker`，内部维护：

- `SSHClient`
- `SFTPClient`
- `connected_at`
- `last_used_at`
- `connection_state`

## 14.2 连接建立

### password 认证

```python
SSHClient.connect(
    hostname=host,
    port=port,
    username=username,
    password=password,
    timeout=connect_timeout_sec,
    look_for_keys=False,
    allow_agent=False,
)
```

### private key 认证

1. 读取私钥路径
2. 如有 passphrase，从 keyring 取
3. 加载私钥对象
4. connect

## 14.3 host key 规则

### strict

- 必须存在于 `%APPDATA%/SFTPAutoSync/known_hosts`
- 不存在则连接失败

### tofu

- 首次连接若 host key 不存在，则自动保存到 `known_hosts`
- 后续若 host key 变化，则连接失败并记录错误

## 14.4 断线恢复

以下异常发生后必须丢弃当前连接并重连：

- socket error
- SSHException
- EOFError
- SFTP session closed
- Transport inactive

策略：

1. 当前任务重试
2. 连接对象置空
3. 下一个任务前自动 reconnect

---

## 15. SyncEngine 详细职责

`SyncEngine` 是运行时总协调器。

## 15.1 职责

1. 启动/停止 watchdog
2. 启动/停止 aggregator
3. 启动/停止 per-server workers
4. 启动 startup rescan
5. 维护 mapping->observer、server->worker 映射
6. 接收 worker 状态事件，转发到 UI
7. 提供：
   - `start_all()`
   - `stop_all()`
   - `reload_config()`
   - `start_mapping(mapping_id)`
   - `stop_mapping(mapping_id)`

## 15.2 约束

1. 不能直接做上传
2. 不能直接操作 GUI widget
3. 只能通过 signal / callback 向 UI 报告状态

---

## 16. 关键类与接口签名

以下接口是实现约束，文件名可固定，方法名尽量按此实现。

## 16.1 ValidationService

```python
class ValidationService:
    def validate_server(self, data: ServerProfile, *, password_present: bool) -> list[str]: ...
    def validate_mapping(self, data: SyncMapping, existing_mappings: list[SyncMapping]) -> list[str]: ...
```

## 16.2 ServerRepository

```python
class ServerRepository:
    def list_all(self) -> list[ServerProfile]: ...
    def list_enabled(self) -> list[ServerProfile]: ...
    def get(self, server_id: int) -> ServerProfile | None: ...
    def create(self, item: ServerProfile) -> int: ...
    def update(self, item: ServerProfile) -> None: ...
    def delete(self, server_id: int) -> None: ...
```

## 16.3 MappingRepository

```python
class MappingRepository:
    def list_all(self) -> list[SyncMapping]: ...
    def list_enabled(self) -> list[SyncMapping]: ...
    def list_by_server(self, server_id: int) -> list[SyncMapping]: ...
    def get(self, mapping_id: int) -> SyncMapping | None: ...
    def create(self, item: SyncMapping) -> int: ...
    def update(self, item: SyncMapping) -> None: ...
    def delete(self, mapping_id: int) -> None: ...
```

## 16.4 StateRepository

```python
class StateRepository:
    def get(self, mapping_id: int, relative_path: str) -> SyncStateRecord | None: ...
    def upsert_success(self, mapping_id: int, relative_path: str, snapshot: FileSnapshot, remote_path: str) -> None: ...
    def upsert_failure(self, mapping_id: int, relative_path: str, remote_path: str, error: str) -> None: ...
    def delete(self, mapping_id: int, relative_path: str) -> None: ...
    def list_by_mapping(self, mapping_id: int) -> list[SyncStateRecord]: ...
```

## 16.5 HistoryRepository

```python
class HistoryRepository:
    def add(self, *, mapping_id: int | None, server_id: int | None, action: str,
            relative_path: str | None, remote_path: str | None, status: str,
            message: str, source: str | None) -> None: ...
    def list_recent(self, limit: int = 500) -> list[dict]: ...
    def prune(self, keep_rows: int = 20000) -> None: ...
```

## 16.6 SecretStore

```python
class SecretStore:
    def set_server_password(self, server_id: int, value: str) -> None: ...
    def get_server_password(self, server_id: int) -> str | None: ...
    def delete_server_password(self, server_id: int) -> None: ...

    def set_key_passphrase(self, server_id: int, value: str) -> None: ...
    def get_key_passphrase(self, server_id: int) -> str | None: ...
    def delete_key_passphrase(self, server_id: int) -> None: ...
```

## 16.7 PathMapper

```python
class PathMapper:
    def is_ignored(self, mapping: SyncMapping, abs_path: Path) -> bool: ...
    def to_relative_path(self, mapping: SyncMapping, abs_path: Path) -> str: ...
    def to_remote_path(self, mapping: SyncMapping, relative_path: str) -> str: ...
```

## 16.8 ConnectionManager

```python
class ConnectionManager:
    def connect(self, server: ServerProfile) -> tuple[paramiko.SSHClient, paramiko.SFTPClient]: ...
    def close(self) -> None: ...
    def is_alive(self) -> bool: ...
```

## 16.9 Uploader / RemoteOps

```python
class RemoteOps:
    def ensure_remote_dir(self, sftp, remote_dir: str) -> None: ...
    def remove_file_if_exists(self, sftp, remote_path: str) -> None: ...
    def stat_or_none(self, sftp, remote_path: str): ...

class Uploader:
    def wait_until_stable(self, local_path: Path) -> FileSnapshot: ...
    def upload_file(self, sftp, local_path: Path, remote_path: str) -> FileSnapshot: ...
    def delete_file(self, sftp, remote_path: str) -> None: ...
```

## 16.10 EventAggregator

```python
class EventAggregator(threading.Thread):
    def submit_raw_event(self, event: dict) -> None: ...
    def run(self) -> None: ...
    def stop(self) -> None: ...
```

原始 event 结构：

```python
{
    "mapping_id": int,
    "server_id": int,
    "event_type": "created|modified|deleted|moved",
    "src_path": str | None,
    "dest_path": str | None,
    "is_directory": bool,
    "ts": float,
}
```

## 16.11 Dispatcher

```python
class Dispatcher:
    def dispatch(self, task: SyncTask) -> None: ...
```

## 16.12 ServerWorker

```python
class ServerWorker(threading.Thread):
    def __init__(self, server_id: int, queue: PriorityQueue, ...): ...
    def run(self) -> None: ...
    def stop(self) -> None: ...
```

---

## 17. ServerWorker 主循环

```python
while not stopped:
    task = queue.get(timeout=0.5)
    emit_status(task, RUNNING)

    try:
        ensure_connected()
        if task.action == UPSERT:
            snapshot = uploader.wait_until_stable(local_path)
            uploader.upload_file(sftp, local_path, task.remote_path)
            state_repo.upsert_success(...)
            history_repo.add(status="success", ...)
            emit_status(task, SUCCESS)

        elif task.action == DELETE:
            uploader.delete_file(sftp, task.remote_path)
            state_repo.delete(...)
            history_repo.add(status="success", ...)
            emit_status(task, SUCCESS)

    except RetryableError as e:
        if task.retry_count < max_retries:
            requeue_with_backoff(task)
        else:
            state_repo.upsert_failure(...)
            history_repo.add(status="failed", message=str(e), ...)
            emit_status(task, FAILED)

    except Exception as e:
        discard_connection()
        if task.retry_count < max_retries:
            requeue_with_backoff(task)
        else:
            state_repo.upsert_failure(...)
            history_repo.add(status="failed", message=str(e), ...)
            emit_status(task, FAILED)

    finally:
        queue.task_done()
```

---

## 18. watchdog 事件处理实现规则

`event_handler.py` 只做四件事：

1. 判断属于哪个 mapping
2. 过滤 disabled mapping
3. 过滤 ignore / 目录
4. 把标准化后的 raw event 丢给 aggregator

禁止：

1. 禁止直接上传
2. 禁止直接写数据库
3. 禁止直接操作 UI

---

## 19. GUI 规格

## 19.1 MainWindow

布局建议：

- 左侧导航
  - Dashboard
  - Servers
  - Mappings
  - Logs
  - Settings
- 右侧页面
- 底部状态栏
  - engine state
  - queue length
  - active workers
  - last error

## 19.2 DashboardPage

显示：

1. 总服务器数 / 启用服务器数
2. 总映射数 / 运行中映射数
3. 各服务器连接状态
4. 各 worker 队列长度
5. 最近 20 条同步记录
6. 当前最后错误

## 19.3 ServersPage

表格列：

- name
- host
- port
- username
- auth_type
- host_key_policy
- enabled
- last_test_result
- updated_at

操作按钮：

- Add
- Edit
- Delete
- Test Connection
- Enable / Disable

## 19.4 ServerDialog 字段

1. Name
2. Host
3. Port
4. Username
5. Auth Type（password / private key）
6. Password（auth_type=password 时显示）
7. Private Key Path（auth_type=private_key 时显示）
8. Key Passphrase（可空）
9. Connect Timeout
10. Host Key Policy（strict / tofu）
11. Enabled

保存逻辑：

- 先做表单校验
- 再保存 server
- 再保存 secrets 到 keyring

## 19.5 MappingsPage

表格列：

- name
- server_name
- local_dir
- remote_dir
- recursive
- delete_policy
- startup_rescan
- enabled
- updated_at

操作按钮：

- Add
- Edit
- Delete
- Enable / Disable
- Open Local Dir

## 19.6 MappingDialog 字段

1. Name
2. Server（下拉）
3. Local Directory（目录选择）
4. Remote Directory
5. Recursive
6. Delete Policy
7. Startup Rescan
8. Ignore Patterns（多行文本，每行一个）
9. Note
10. Enabled

保存逻辑：

- 先解析 ignore patterns
- 先校验 local_dir 是否存在
- 再校验与其他 mapping 是否重叠

## 19.7 LogsPage

1. 最近历史表格
2. 过滤条件
   - mapping
   - server
   - status
   - keyword
3. 支持刷新
4. 支持复制错误信息

## 19.8 SettingsPage

V1 仅保留：

1. App Data Directory（只读）
2. Log Retention Rows
3. Debounce Milliseconds（可选暴露）
4. Startup Auto Start Engine（可选）
5. Save

---

## 20. UI 与后台通信规则

1. 所有后台线程到 UI 的更新，必须走 Qt Signal
2. 后台线程禁止直接访问 QWidget
3. UI 操作配置变更后，通过 `SyncEngine.reload_config()` 重新加载
4. reload 过程：
   - 停止 observer
   - 停止 aggregator
   - 停止 workers
   - 重新读库
   - 重新启动所有运行组件

V1 不做热更新局部 patch，直接完整 reload，逻辑更稳。

---

## 21. 日志与历史

## 21.1 logging

至少两个 handler：

1. `app.log`：INFO 以上
2. `error.log`：ERROR 以上

建议滚动：

```txt
maxBytes = 5MB
backupCount = 5
```

## 21.2 sync_history 记录时机

以下动作必须写入 history：

1. upload success
2. upload failed
3. delete success
4. delete failed
5. skipped（ignore / missing / symlink / directory）
6. test connection result

---

## 22. 错误分类

定义统一错误基类，至少区分：

```python
class AppError(Exception): ...
class ValidationError(AppError): ...
class RetryableError(AppError): ...
class NonRetryableError(AppError): ...
class ConnectionError(AppError): ...
class AuthError(AppError): ...
class HostKeyError(AppError): ...
class UploadError(AppError): ...
```

分类规则：

### Retryable

- 网络断开
- session closed
- file still changing
- temporary permission / busy（可视情况）

### NonRetryable

- 本地路径不存在（delete 场景除外）
- 私钥路径无效
- 密码缺失
- host key mismatch
- 远程权限永久拒绝（可先按 non-retryable 处理）
- mapping 非法

---

## 23. 代码实现硬约束

1. 禁止在 GUI 线程里调用 Paramiko
2. 禁止共享 SQLite connection 到多个线程
3. 禁止共享同一个 SFTPClient 到多个 worker
4. 禁止 watchdog 回调里直接上传
5. 禁止明文密码写入 SQLite
6. 禁止默认执行远程删除
7. 禁止对目录事件直接上传
8. 禁止自动处理 symlink
9. 禁止映射重叠
10. 禁止把 remote path 当 Windows 路径拼接

---

## 24. 默认参数

```python
DEFAULT_PORT = 22
DEFAULT_CONNECT_TIMEOUT_SEC = 10
DEFAULT_DEBOUNCE_MS = 800
DEFAULT_AGGREGATOR_TICK_MS = 200
DEFAULT_STABILITY_CHECK_INTERVAL_MS = 300
DEFAULT_STABILITY_MAX_CHECKS = 5
DEFAULT_HISTORY_KEEP_ROWS = 20000
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_DELAYS = [1, 2, 5, 10, 20]
```

---

## 25. 开发顺序（必须按此里程碑）

## M1：基础模型与持久化

目标：

1. 完成 `schema.sql`
2. 完成 repo
3. 完成 `SecretStore`
4. 完成 `ValidationService`

验收：

- 能创建 / 更新 / 删除 server
- 能创建 / 更新 / 删除 mapping
- secrets 不落库
- 映射重叠校验生效

## M2：SFTP 基础能力

目标：

1. 完成 `ConnectionManager`
2. 完成 `RemoteOps`
3. 完成 `Uploader`
4. 完成 `Test Connection`

验收：

- 能连接密码认证服务器
- 能连接私钥认证服务器
- 能创建远程目录
- 能上传单文件
- 能删除单文件
- host key strict / tofu 工作正常

## M3：事件监听与聚合

目标：

1. 完成 watchdog 监听
2. 完成 `EventAggregator`
3. 完成 `Dispatcher`
4. 完成 `ServerWorker`

验收：

- 保存本地文件后会自动上传
- 连续多次保存不会重复疯狂上传
- 同一文件只会生成合理数量任务
- 失败会重试
- 成功后会写 state/history

## M4：启动补扫

目标：

1. 完成 `StartupRescanService`
2. 加入引擎启动流程

验收：

- 应用关闭期间改动的文件，重启后会自动上传
- 未变更文件不会重复上传
- 开启 delete_policy 时，本地删除可在重启后补删远程

## M5：GUI

目标：

1. 完成 MainWindow
2. 完成 ServersPage / MappingsPage
3. 完成 Dashboard / Logs / Settings
4. 完成 signal 联动

验收：

- 全部配置可在 GUI 完成
- 测试连接可用
- 状态与日志可见
- 配置修改后 reload 生效

## M6：打包与发布

目标：

1. 加入 PyInstaller 构建脚本
2. 验证 Windows 运行
3. 验证 app data 持久化

验收：

- 可打包
- 首次运行自动建库
- 关闭重开配置仍存在

---

## 26. 最低测试集

## 26.1 单元测试

1. `ValidationService`
2. `PathMapper`
3. `EventAggregator` 去重规则
4. `Uploader.wait_until_stable`
5. `StateRepository`
6. `StartupRescanService`

## 26.2 集成测试

1. 本地临时目录 + mocked Paramiko
2. 创建文件 -> 自动上传
3. 修改文件 -> 自动上传
4. 删除文件 -> delete_policy=ignore 时不删远端
5. 删除文件 -> delete_policy=delete_file 时删远端
6. 断线后自动重连
7. startup rescan 正常补传

## 26.3 人工回归清单

1. 大文件保存中不会上传半文件
2. 私钥带口令可连接
3. 多服务器并行运行互不影响
4. GUI 不会因网络慢卡死
5. 修改配置后 reload 正常
6. known_hosts 持久化有效

---

## 27. 关键边界条件

1. 文件在队列中时被删除
   - UPSERT 执行前不存在 -> 记 skipped 或 delete
2. 文件在上传时再次被修改
   - 当前上传完成后，后续新事件会再次触发 UPSERT
3. 本地路径包含中文
   - 必须支持
4. 远程路径已有旧文件
   - 上传后覆盖
5. 远程父目录不存在
   - 自动创建
6. 映射被禁用
   - 停止监听，不再处理新任务
7. 应用退出时队列未清空
   - 下次启动由 rescan 恢复
8. 同一服务器多个 mapping
   - 共享同一个 worker 和连接
9. 服务器短时不可达
   - 自动重试，不崩溃
10. 私钥路径失效
   - 测试连接和 worker 明确报错

---

## 28. 参考实现伪代码

## 28.1 启动流程

```python
def bootstrap():
    ensure_app_dirs()
    setup_logging()
    run_migrations()

    app = QApplication(sys.argv)
    window = MainWindow()

    sync_engine = SyncEngine(...)
    window.bind_engine(sync_engine)

    window.load_initial_data()
    sync_engine.start_all()

    window.show()
    return app.exec()
```

## 28.2 原始事件处理

```python
def on_any_event(event):
    mapping = mapping_lookup(event.src_path or event.dest_path)
    if not mapping or not mapping.enabled:
        return

    if event.is_directory:
        return

    raw = normalize_watchdog_event(mapping, event)
    if raw is None:
        return

    aggregator.submit_raw_event(raw)
```

## 28.3 聚合器

```python
pending = {}  # key -> pending event

while not stopped:
    drain_raw_events_into_pending()
    now = time.time()

    for key, item in list(pending.items()):
        if item.deadline_ts <= now:
            task = build_sync_task(item)
            dispatcher.dispatch(task)
            del pending[key]

    sleep(AGGREGATOR_TICK_MS / 1000)
```

## 28.4 补扫

```python
for mapping in mapping_repo.list_enabled():
    if not mapping.startup_rescan:
        continue

    for file in walk_files(mapping.local_dir):
        if path_mapper.is_ignored(mapping, file):
            continue
        rel = path_mapper.to_relative_path(mapping, file)
        snap = snapshot(file)
        state = state_repo.get(mapping.id, rel)
        if state is None or state.last_local_size != snap.size or state.last_local_mtime_ns != snap.mtime_ns:
            enqueue_upsert(mapping, file, rel, source="startup_rescan", priority=10)

    if mapping.delete_policy == DeletePolicy.DELETE_FILE:
        existing = collect_local_relative_paths(mapping)
        for state in state_repo.list_by_mapping(mapping.id):
            if state.relative_path not in existing:
                enqueue_delete(mapping, state.relative_path, source="startup_rescan", priority=10)
```

---

## 29. 首版交付标准

满足以下即视为 V1 完成：

1. 用户可以在 GUI 中配置多个服务器
2. 用户可以在 GUI 中配置多个目录映射
3. 支持密码和私钥两种认证
4. 支持自定义端口
5. 配置可持久化
6. 本地文件新增 / 修改后会自动上传
7. 启动时会补扫遗漏变更
8. 多服务器可以同时运行
9. 失败不会导致程序崩溃
10. GUI 不会因上传阻塞
11. 默认不删除远端
12. 日志和历史可查看

---

## 30. V2 可扩展项（本轮不实现）

1. 系统托盘
2. 开机自启
3. 文件类型白名单 / 黑名单
4. 带宽限制
5. 任务暂停 / 恢复
6. 远端目录浏览器
7. 手动全量同步按钮
8. 手动清理 host key
9. 配置导入导出
10. 失败任务手动重试
11. 多 worker/服务器并发度可配置

---

## 31. AI 编程执行要求

给 AI 编程工具的约束：

1. 先生成项目骨架与 `schema.sql`
2. 再实现 repo 和校验层
3. 再实现 SFTP 层
4. 再实现 watcher / aggregator / worker
5. 再实现 GUI
6. 每一层完成后先写对应测试，再继续下一层
7. 不要跳过 `startup_rescan`
8. 不要跳过 `keyring`
9. 不要把所有逻辑塞进一个文件
10. 所有核心逻辑都要可单测
11. 所有线程退出都要可控，支持应用优雅关闭
12. 所有异常必须记录到日志和 history（能记录的场景都记录）

---

## 32. requirements.txt 建议

```txt
paramiko
watchdog
PySide6
keyring
```

开发依赖可额外加入：

```txt
pytest
pytest-qt
pyinstaller
```
