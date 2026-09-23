# 新设备恢复指南

GitHub 仓库保存的是程序和说明，**不保存你的真实聊天记录、数据库、密码、Token 或本机坐标**。要完整恢复自己的历史归档，需要同时拥有：

1. 本仓库的 GitHub 地址；
2. 单独加密保存的 `var/raw/*.jsonl` 原始归档副本；
3. 可选的旧 SQLite 副本（它可从 JSONL 重建）；
4. 新电脑上的 Windows x64、Python 3.11+ 和目标程序。

## 1. 恢复程序

```powershell
git clone https://github.com/tudoufuwu/ymjh-chuanyin-collector.git
cd ymjh-chuanyin-collector
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m ymjh_chuanyin init --root .
```

仓库不依赖你旧电脑的用户名、盘符、Python 安装位置、域名或 Tunnel 配置。

## 2. 恢复历史 JSONL

把自己**已加密备份并安全取回**的 JSONL 文件复制到：

```text
var\raw\
```

不要把它们放到仓库根目录，也不要执行 `git add var`。

## 3. 重新生成 SQLite

```powershell
.\.venv\Scripts\python.exe -m ymjh_chuanyin rebuild --root . --replace
```

该命令会扫描 `var\raw\` 下的所有 `.jsonl` 分段，按 `event_id` 去重创建：

```text
var\archive\chat-archive.db
```

这就是为什么 JSONL 是首要恢复源，SQLite 是可重建的查询层。

## 4. 恢复本地网页

```powershell
.\.venv\Scripts\python.exe -m ymjh_chuanyin serve --root .
```

浏览器访问 <http://127.0.0.1:8766>。

## 5. 恢复新的实时采集

安装并启动你有权访问的目标程序后，查找 PID：

```powershell
Get-Process wyclx64 | Select-Object Id, ProcessName
```

然后：

```powershell
.\scripts\start-local.ps1 -GamePid <PID>
```

它会写入新电脑自身的 `var/`。不需要也不应从旧电脑复制密码、Tunnel 配置、捕获心跳、运行日志、数据库 WAL/SHM 文件或旧的绝对路径配置。

## 备份建议

- 优先备份 `var/raw/`，并使用设备加密、加密压缩包或你信任的端到端加密存储；
- 可以额外备份 `var/archive/chat-archive.db`，但它不是唯一恢复来源；
- 每次备份都应确保 JSONL 文件已完整写入一行结尾，避免复制正在增长的活动文件；
- 真实聊天可能包含个人信息。备份、同步或分享前必须确认法律、平台规则和相关人员的隐私边界。
