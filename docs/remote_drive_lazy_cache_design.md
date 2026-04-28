# 远程目录映射为 Windows 盘符的新增功能设计

## 1. 背景

当前程序已经支持：

- 将本地目录映射到远程服务器目录。
- 监听本地文件变化并自动上传到 SFTP 服务器。
- 使用 `%APPDATA%/SFTPAutoSync/cache/` 作为运行期缓存目录。

当前程序还不支持：

- 将远程服务器目录映射成一个可在 Windows 资源管理器中访问的盘符。
- 浏览远程目录结构但不立即下载文件内容。
- 当用户或程序真正读取文件时再按需下载。
- 对已下载文件进行本次运行期内的缓存复用。
- 对缓存文件的修改进行自动上传回远程服务器。

本设计文档用于规划上述能力的新增方案。这里的“映射出一个 U 盘/远程盘”，实际含义是：

- 在 Windows 中挂载一个虚拟盘符，例如 `R:`。
- 盘符背后映射到某个 SFTP 服务器上的远程目录。
- 用户像操作普通磁盘一样浏览目录、打开文件、编辑文件。
- 文件内容采用“懒下载 + 本地缓存 + 修改后回传”的模型。

## 2. 核心目标

### 2.1 功能目标

新增一个“远程盘映射”功能，允许用户：

1. 选择一个服务器配置。
2. 指定一个远程根目录。
3. 指定一个 Windows 盘符。
4. 挂载后在资源管理器中看到远程目录中的文件和子目录。
5. 文件列表显示时只拉取元数据，不下载文件内容。
6. 当文件首次被读取时，才下载到本地缓存目录。
7. 同一进程运行期间，如果某个文件已经下载过，则后续读取直接使用缓存文件，不重复下载。
8. 当缓存文件被修改后，自动上传回远程服务器。
9. 程序重启后，清空“本次运行期已下载文件映射变量”，重新按需下载。

### 2.2 非目标

本阶段不做以下能力：

1. 不做完整双向实时同步引擎。
2. 不做离线编辑后重连冲突自动合并。
3. 不做块级增量传输。
4. 不做 Linux/macOS 虚拟盘支持。
5. 不做将缓存跨进程永久信任。
6. 不做文件权限、owner、group、ACL 的完整映射。
7. 不做符号链接支持。
8. 不做真正的物理 U 盘模拟，只做 Windows 虚拟文件系统挂载。

## 3. 用户体验定义

### 3.1 用户配置项

远程盘映射建议新增以下配置：

- 映射名称
- 服务器 ID
- 远程根目录
- Windows 盘符
- 是否开机后自动挂载
- 只读模式开关
- 本地缓存根目录
- 缓存文件大小上限
- 单文件下载超时
- 单文件上传超时
- 空闲自动断开时间

### 3.2 用户可见行为

挂载成功后：

1. 在 Windows 中显示一个盘符，例如 `R:`。
2. 打开 `R:` 时看到远程目录树。
3. 浏览目录时只展示远程目录项，不拉全量文件内容。
4. 双击某文件时，如果未缓存，则先下载到本地缓存，再把内容返回给读取方。
5. 再次打开同一文件时，如果本次运行已缓存，则直接从缓存读取。
6. 如果用编辑器修改该文件，则标记为 dirty，并异步上传。
7. 上传成功后更新缓存状态。
8. 程序退出或远程盘卸载后，本次运行期内存映射清空。

## 4. 总体设计原则

### 4.1 元数据和文件内容分离

远程盘至少维护两类缓存：

1. 目录/文件元数据缓存
2. 文件内容缓存

其中：

- 元数据缓存用于列目录、查询属性、显示文件大小和修改时间。
- 文件内容缓存用于实际读取和写入。

### 4.2 运行期内存映射是缓存命中依据

必须维护一个仅在本次程序运行期间存在的内存映射变量，用于记录：

- 哪些远程文件已经下载过
- 对应缓存文件路径
- 缓存版本信息
- 是否被修改
- 是否正在下载/上传

关键约束：

- 只要程序还在运行，且该变量中存在记录，就优先使用缓存文件。
- 程序重启后，该变量必须清空。
- 即使磁盘缓存文件仍然存在，重启后也不能直接视为可信缓存命中，必须重新下载或重新校验。

### 4.3 缓存文件落磁盘，但“是否可用”由内存索引决定

推荐方案：

- 文件内容下载后保存到 `%APPDATA%/SFTPAutoSync/cache/remote_drives/<mount_id>/...`
- 运行期内存变量保存 `remote_path -> cache_entry`
- 卸载或应用退出时清空内存变量
- 启动时清理对应挂载目录下的旧缓存，避免误用旧数据

这样可以同时满足：

- 文件内容可被普通 Windows 程序读取
- 已下载文件在本次运行期间不重复从服务器下载
- 重启后必须重新下载的要求

## 5. 技术路线

## 5.1 虚拟文件系统层

建议采用 Dokany 作为 Windows 虚拟盘驱动适配层。

原因：

1. 当前仓库 README 已明确指向 Dokany 迁移方向。
2. 该需求本质是“把自定义文件系统挂载为 Windows 盘符”。
3. 普通 SFTP API 本身不能直接生成盘符，必须借助文件系统驱动层。

建议在工程中抽象一层：

- `VirtualDriveAdapter`

其职责：

- 对接 Dokany 回调
- 将 Windows 文件系统请求翻译成应用内部操作
- 与远程目录服务、缓存服务协作

### 5.2 远程盘核心子系统

建议新增一个独立子系统 `remote_drive`，不要直接混在现有本地监听上传逻辑里。

原因：

- “本地目录监听上传”和“虚拟盘懒下载回写”虽然都使用 SFTP，但事件来源不同。
- 虚拟盘场景更接近一个按需文件系统，不是普通 watcher。
- 如果混到同一套任务流中，后续难以控制回环、锁和状态机。

## 6. 模块划分建议

建议新增如下目录：

```text
sftp_auto_sync/
  remote_drive/
    models.py
    enums.py
    mount_manager.py
    session.py
    metadata_cache.py
    content_cache.py
    cache_index.py
    remote_tree_service.py
    file_transfer_service.py
    upload_scheduler.py
    path_resolver.py
    dokany_adapter.py
    conflict_detector.py
```

### 6.1 模块职责

`models.py`

- 定义远程盘映射配置
- 定义缓存条目
- 定义目录项快照
- 定义挂载会话对象

`mount_manager.py`

- 创建、启动、停止挂载会话
- 管理多个盘符映射
- 防止同一盘符重复挂载

`session.py`

- 表示单个远程盘运行实例
- 持有 SFTP 连接池、缓存索引、上传队列、会话状态

`metadata_cache.py`

- 缓存目录列表和文件 stat 信息
- 提供 TTL、失效和主动刷新机制

`content_cache.py`

- 管理缓存文件目录
- 下载、读取、写入、删除本地缓存文件

`cache_index.py`

- 保存本次运行期内存映射
- 决定缓存是否命中

`remote_tree_service.py`

- 从远程读取目录内容
- 将远程路径转换为虚拟盘可见目录项

`file_transfer_service.py`

- 执行远程下载、上传、重命名、删除等 SFTP 操作

`upload_scheduler.py`

- 负责 dirty 文件的延迟上传、合并、重试和串行化

`dokany_adapter.py`

- 对接 Dokany 回调
- 处理 `list/open/read/write/flush/close/create/delete/move/stat`

## 7. 数据模型设计

### 7.1 新增持久化配置模型

建议新增 `RemoteDriveMapping`：

```python
@dataclass(slots=True)
class RemoteDriveMapping:
    id: int | None = None
    name: str = ''
    server_id: int = 0
    remote_root: str = ''
    drive_letter: str = ''
    enabled: bool = True
    auto_mount: bool = False
    read_only: bool = False
    cache_root: str | None = None
    file_cache_size_limit_mb: int = 1024
    metadata_ttl_sec: int = 10
    download_timeout_sec: int = 60
    upload_timeout_sec: int = 60
    note: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
```

对应新增数据库表，例如：

- `remote_drive_mappings`

该表用于保存“哪个服务器的哪个目录挂载到哪个盘符”。

### 7.2 运行期缓存条目模型

建议定义：

```python
@dataclass(slots=True)
class CachedFileEntry:
    remote_path: str
    local_cache_path: str
    remote_size: int | None
    remote_mtime_ns: int | None
    local_size: int | None
    local_mtime_ns: int | None
    downloaded_at: float
    last_access_at: float
    is_dirty: bool
    is_downloading: bool
    is_uploading: bool
    open_handle_count: int
```

### 7.3 运行期目录项模型

```python
@dataclass(slots=True)
class RemoteDirEntry:
    remote_path: str
    name: str
    is_dir: bool
    size: int
    mtime_ns: int | None
```

## 8. 关键运行期内存结构

这是本功能的核心。

### 8.1 文件缓存索引

建议在每个挂载会话内维护：

```python
cache_index: dict[str, CachedFileEntry]
```

键：

- 远程文件绝对路径，例如 `/var/www/app/config.json`

值：

- 当前运行期缓存条目

用途：

1. 判断某文件是否已在本次运行中下载。
2. 找到对应本地缓存文件。
3. 判断是否 dirty。
4. 判断是否正在上传/下载。
5. 支持读写锁和并发控制。

### 8.2 目录元数据索引

建议维护：

```python
dir_index: dict[str, list[RemoteDirEntry]]
stat_index: dict[str, RemoteDirEntry]
```

用途：

- 列目录时减少重复远程请求
- `GetFileInformation` / `stat` 这类查询快速返回

### 8.3 打开句柄表

建议维护：

```python
open_handles: dict[int, OpenFileHandle]
```

用途：

- 跟踪某个 Windows 文件句柄对应哪个远程路径
- 区分读句柄和写句柄
- 在 `close/flush` 时决定是否上传

## 9. 读流程设计

### 9.1 列目录

当资源管理器打开某个目录时：

1. Dokany 回调进入 `list directory`
2. 将虚拟盘路径转换为远程路径
3. 查询 `dir_index`
4. 如果命中且未过期，则直接返回缓存元数据
5. 如果未命中或已过期，则调用 SFTP `listdir_attr`
6. 将结果写入 `dir_index` 和 `stat_index`
7. 返回目录项

注意：

- 这里不下载文件内容。
- 只获取目录项名称、类型、大小、mtime。

### 9.2 读取文件内容

当某个程序打开并读取文件时：

1. Dokany 收到 `open/read`
2. 将虚拟路径转换成远程路径
3. 查询 `cache_index`
4. 如果存在条目且本次运行已下载，则直接读取 `local_cache_path`
5. 如果不存在，则进入“按需下载”
6. 下载成功后生成 `CachedFileEntry` 写入 `cache_index`
7. 从本地缓存文件读取并返回

### 9.3 按需下载策略

首次读取文件时：

1. 创建目标缓存文件路径
2. 将状态标记为 `is_downloading=True`
3. 调用 `sftp.get(remote_path, local_cache_path.tmp)`
4. 下载完成后原子重命名为正式缓存文件
5. 记录远程 size / mtime
6. 更新 `cache_index`
7. 清除 `is_downloading`

并发要求：

- 同一文件如果被多个读取请求同时命中未缓存状态，只允许一个下载任务真正执行。
- 其他请求等待该下载完成后共享结果。

## 10. 写流程设计

### 10.1 写入缓存而不是直接远程写

写入时不建议直接对远程文件流式写入，建议流程如下：

1. 若文件未缓存，先下载原文件到本地缓存。
2. Windows 程序对缓存文件执行写入。
3. 标记该文件 `is_dirty=True`。
4. 在 `flush` 或 `close` 时触发上传调度。

理由：

- 与普通编辑器行为兼容性更好。
- 避免远程网络抖动直接影响应用写文件流程。
- 可以把上传重试、合并和失败恢复做在后台。

### 10.2 上传触发点

建议至少在以下时机触发上传：

1. 文件句柄 `flush`
2. 文件句柄 `close`
3. 写后空闲防抖超时，例如 1 到 3 秒

最终策略：

- 多次连续写入合并为一次上传。

### 10.3 上传流程

1. 调度器检查 `is_dirty=True`
2. 若文件仍有写句柄，可延迟上传
3. 若满足上传条件，则读取缓存文件当前内容
4. 上传到远程临时文件，例如 `.filename.__uploading__`
5. 成功后远程原子重命名覆盖目标文件
6. 更新远程 stat
7. 将 `is_dirty=False`
8. 更新 `cache_index` 中的本地和远程版本信息
9. 刷新父目录元数据缓存

### 10.4 上传失败处理

若上传失败：

1. 保留本地缓存文件
2. 保持 `is_dirty=True`
3. 记录错误和重试次数
4. 在 UI 中提示“待上传”
5. 后台按退避策略重试

## 11. 新建、删除、重命名流程

### 11.1 新建文件

当用户在虚拟盘中新建文件时：

1. 先在本地缓存创建空文件
2. 生成 `CachedFileEntry`
3. 标记 `is_dirty=True`
4. 在 `flush/close` 后上传到远程

### 11.2 删除文件

建议定义两阶段行为：

1. 先删除本地缓存文件或标记已删除
2. 再异步删除远程文件

如果远程删除失败：

- 在 UI 中标记失败
- 保留错误记录

### 11.3 重命名文件

优先走远程 `rename`，同时同步本地缓存路径和内存索引：

1. 更新远程路径
2. 更新缓存文件路径
3. 更新 `cache_index` key
4. 更新父目录元数据缓存

若跨目录移动：

- 同样视为 rename 处理，但要刷新源目录和目标目录的元数据缓存。

## 12. 一致性与冲突策略

### 12.1 本阶段采用“单客户端优先”

该功能第一阶段建议采用较保守策略：

- 假设主要由本程序挂载出的虚拟盘修改远程文件。
- 不保证能完美处理“其他客户端同时修改远程同一文件”的冲突。

### 12.2 基础冲突检测

在上传前做轻量检测：

1. 读取缓存条目中的 `remote_mtime_ns` / `remote_size`
2. 上传前对远程再 `stat` 一次
3. 如果发现远程版本已变化，判定冲突

冲突时的建议处理：

1. 默认拒绝直接覆盖
2. 将本地缓存另存为冲突副本
3. 在 UI 中提示冲突
4. 后续再扩展“强制覆盖”选项

## 13. 缓存策略细化

### 13.1 缓存目录布局

建议：

```text
%APPDATA%/SFTPAutoSync/cache/
  remote_drives/
    <mount_id>/
      files/
        <hashed_remote_path>.bin
      meta/
        optional_debug_files
```

说明：

- 缓存文件名不要直接使用原始远程路径，建议 hash 后存储。
- 避免路径过长、非法字符和大小写冲突。

### 13.2 启动时缓存处理

为了满足“程序重启后必须重新下载”的要求，建议：

1. 应用启动时不恢复旧 `cache_index`
2. 挂载远程盘前清空该挂载对应的缓存目录
3. 或者至少将旧缓存标记为不可用并在后台清理

推荐首版直接做：

- 挂载前清空当前挂载目录的旧缓存

这样逻辑最简单，也最符合用户要求。

### 13.3 运行中缓存淘汰

如果单个挂载的缓存总量超过阈值：

- 优先淘汰未打开、未 dirty、最近最少使用的缓存文件

但必须满足：

- 已在 `cache_index` 中且仍有打开句柄的文件不能删除
- `is_dirty=True` 的文件不能删除

## 14. 与现有同步引擎的边界

当前项目已有一套“本地 watcher -> 聚合 -> 上传”的同步链路。

新增远程盘功能时，建议不要直接让 Dokany 挂载目录再被 watchdog 监听，否则容易形成回环：

1. 用户通过远程盘写入缓存文件
2. 本地 watcher 看到缓存目录变化
3. 又当成普通本地映射去上传
4. 与远程盘自己的上传调度重复

因此必须明确：

- 远程盘缓存目录不进入现有 `sync_mappings` 监听范围
- 远程盘上传使用独立的 `upload_scheduler`
- 现有 `sync_engine` 不直接处理远程盘缓存目录事件

## 15. UI 设计建议

建议在现有界面新增一个页面：

- `Remote Drives`

至少包含以下能力：

1. 新建远程盘映射
2. 编辑远程盘映射
3. 删除远程盘映射
4. 挂载
5. 卸载
6. 查看挂载状态
7. 查看缓存状态
8. 查看待上传数量
9. 查看错误日志

表格建议列：

- 名称
- 服务器
- 远程根目录
- 盘符
- 状态
- 只读
- 缓存占用
- 待上传文件数
- 最后错误

## 16. 数据库变更建议

建议新增表：

```sql
CREATE TABLE IF NOT EXISTS remote_drive_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    server_id INTEGER NOT NULL,
    remote_root TEXT NOT NULL,
    drive_letter TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    auto_mount INTEGER NOT NULL DEFAULT 0 CHECK (auto_mount IN (0, 1)),
    read_only INTEGER NOT NULL DEFAULT 0 CHECK (read_only IN (0, 1)),
    cache_root TEXT,
    file_cache_size_limit_mb INTEGER NOT NULL DEFAULT 1024,
    metadata_ttl_sec INTEGER NOT NULL DEFAULT 10,
    download_timeout_sec INTEGER NOT NULL DEFAULT 60,
    upload_timeout_sec INTEGER NOT NULL DEFAULT 60,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(server_id) REFERENCES server_profiles(id) ON DELETE RESTRICT
);
```

首版不建议把运行期缓存状态落库。

原因：

1. 用户明确要求“本次运行的变量映射”。
2. 运行期状态持久化会引入恢复逻辑和脏状态问题。
3. 首版目标是保证运行中命中缓存，重启后重新下载。

## 17. 并发与锁设计

### 17.1 锁粒度

建议至少有三层锁：

1. 挂载级锁
2. 单文件级锁
3. 句柄表锁

单文件级锁可以用：

```python
file_locks: dict[str, threading.RLock]
```

用途：

- 避免同一文件同时下载、上传、重命名、删除互相踩踏。

### 17.2 线程模型

建议：

1. Dokany 回调线程负责接收文件系统请求
2. 远程元数据查询走会话线程池
3. 下载任务走下载线程池
4. 上传任务走上传队列

这样可以避免：

- 在 Dokany 回调中长时间阻塞网络 IO
- 因单个大文件下载导致整个虚拟盘卡住

## 18. 日志与可观测性

需要新增专门的远程盘日志分类：

- 挂载/卸载日志
- 目录浏览日志
- 懒下载日志
- 缓存命中日志
- dirty 标记日志
- 上传调度日志
- 冲突检测日志
- Dokany 回调异常日志

建议关键日志字段：

- mount_id
- drive_letter
- server_id
- remote_path
- cache_path
- action
- duration_ms
- result
- error

## 19. 任务拆分建议

建议按以下阶段实施。

### 阶段 1：数据层和配置层

目标：

- 先把远程盘映射配置落库并接入 UI。

任务：

1. 新增 `RemoteDriveMapping` 模型和枚举。
2. 扩展 `schema.sql` 和 migration。
3. 新增 `remote_drive_mapping_repo.py`。
4. 新增 `remote_drive_service.py`。
5. 新增 UI 页面、表单和基础 CRUD。

交付结果：

- 用户可以配置远程盘映射，但暂时不能真正挂载。

### 阶段 2：缓存子系统

目标：

- 先实现不依赖 Dokany 的缓存核心能力。

任务：

1. 实现 `cache_index.py`
2. 实现 `content_cache.py`
3. 实现 `metadata_cache.py`
4. 实现按需下载逻辑
5. 实现 dirty 标记和上传调度
6. 实现单文件锁

交付结果：

- 可以通过内部接口完成“列目录、懒下载、缓存命中、修改后上传”的核心闭环。

### 阶段 3：虚拟盘适配层

目标：

- 将缓存核心接到 Dokany。

任务：

1. 抽象 `VirtualDriveAdapter`
2. 实现 `dokany_adapter.py`
3. 接入 open/read/write/flush/close/list/stat/create/delete/rename
4. 处理 Windows 特殊访问模式和临时文件行为

交付结果：

- 可以在 Windows 中真实挂载盘符。

### 阶段 4：状态管理和 UI 联动

目标：

- 可视化挂载状态、错误和缓存指标。

任务：

1. UI 显示挂载状态
2. UI 显示缓存占用
3. UI 显示待上传数量
4. UI 显示冲突和重试状态

### 阶段 5：稳定性增强

目标：

- 处理边界问题和复杂场景。

任务：

1. 冲突检测
2. LRU 缓存淘汰
3. 自动重连
4. 挂载异常恢复
5. 大文件性能优化

## 20. 建议新增/修改文件清单

基于当前项目结构，建议至少涉及以下文件。

新增：

- `sftp_auto_sync/domain/remote_drive_models.py`
- `sftp_auto_sync/infra/db/remote_drive_mapping_repo.py`
- `sftp_auto_sync/services/remote_drive_service.py`
- `sftp_auto_sync/remote_drive/models.py`
- `sftp_auto_sync/remote_drive/cache_index.py`
- `sftp_auto_sync/remote_drive/content_cache.py`
- `sftp_auto_sync/remote_drive/metadata_cache.py`
- `sftp_auto_sync/remote_drive/session.py`
- `sftp_auto_sync/remote_drive/mount_manager.py`
- `sftp_auto_sync/remote_drive/file_transfer_service.py`
- `sftp_auto_sync/remote_drive/upload_scheduler.py`
- `sftp_auto_sync/remote_drive/dokany_adapter.py`
- `sftp_auto_sync/ui/pages/remote_drives_page.py`
- `sftp_auto_sync/ui/dialogs/remote_drive_dialog.py`
- `sftp_auto_sync/tests/test_remote_drive_cache_index.py`
- `sftp_auto_sync/tests/test_remote_drive_content_cache.py`
- `sftp_auto_sync/tests/test_remote_drive_upload_scheduler.py`

修改：

- `sftp_auto_sync/domain/models.py`
- `sftp_auto_sync/infra/db/schema.sql`
- `sftp_auto_sync/infra/db/migration_runner.py`
- `sftp_auto_sync/app/bootstrap.py`
- `sftp_auto_sync/ui/main_window.py`
- `README.md`

## 21. 测试方案

### 21.1 单元测试

必须覆盖：

1. 首次读取触发下载
2. 第二次读取命中内存缓存索引
3. 重启后不命中旧缓存
4. dirty 文件 close 后触发上传
5. 上传失败后保留 dirty 状态
6. 并发读取同一文件只下载一次
7. rename 后索引迁移正确
8. 删除后索引和缓存清理正确

### 21.2 集成测试

必须覆盖：

1. 挂载目录可列出远程文件
2. 文本编辑器打开文件时自动下载
3. 连续读取不重复下载
4. 修改保存后远程文件已更新
5. 断网后写入产生待上传状态
6. 重连后自动完成回传

### 21.3 手工验证重点

重点验证 Windows 常见应用行为：

1. 资源管理器预览
2. 记事本打开/保存
3. VS Code 打开目录
4. Office 类应用另存为
5. 大文件读取
6. 中文文件名
7. 深层目录

## 22. 主要风险

### 22.1 Dokany 接入复杂度

风险：

- Windows 文件系统回调细节较多，和普通业务逻辑差异大。

应对：

- 先把缓存和传输核心做成独立服务，再接 Dokany。

### 22.2 编辑器行为复杂

风险：

- 很多编辑器不是“原地修改”，而是“写临时文件 -> rename 覆盖”。

应对：

- 必须完整支持 create/write/flush/rename/delete 的组合流程。

### 22.3 远程并发修改冲突

风险：

- 其他客户端可能在本地缓存存在期间改了远程文件。

应对：

- 首版做上传前 stat 检测，先拒绝静默覆盖。

### 22.4 缓存占用膨胀

风险：

- 大量文件被打开后缓存增长过快。

应对：

- 加缓存上限和 LRU 淘汰。

## 23. 推荐实施顺序

如果按开发效率和风险控制排序，推荐顺序如下：

1. 先补数据模型和数据库表。
2. 再做远程树读取和元数据缓存。
3. 再做内容缓存和运行期 `cache_index`。
4. 再做上传调度器。
5. 通过内部接口把“读一次下载、再读命中缓存、修改后上传”跑通。
6. 最后接 Dokany 盘符挂载。
7. 最后补 UI、日志、错误展示和稳定性增强。

## 24. 最终结论

这个需求本质上不是简单的“再加一个 watcher”，而是要新增一个“基于 SFTP 的 Windows 虚拟文件系统”子系统。

其中最关键的设计点有三个：

1. 目录浏览只拉元数据，不拉文件内容。
2. 文件内容首次读取才下载到本地缓存。
3. 本次运行期间必须维护一个仅驻留内存的 `remote_path -> cache_entry` 映射，用它决定缓存命中；程序重启后该映射失效，缓存不再可信，需要重新下载。

按本文档的拆分方式推进，能够在不破坏现有“本地目录自动上传”架构的前提下，较清晰地落地远程盘映射能力。
