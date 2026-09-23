# 架构说明

## 数据流

```text
有权访问的 Windows 目标进程
  │  只读 OpenProcess / ReadProcessMemory
  ▼
collector/watch_memory_chat.py
  │  默认不写地址、完整序列字段或会话样式数据
  ▼
var/raw/chat-events.jsonl
  │
  ▼
archive/sqlite_store.py
  │  event_id 唯一约束、频道分类、SQLite WAL
  ▼
var/archive/chat-archive.db
  │  只读连接
  ▼
web/server.py → 127.0.0.1:8766
```

## 组件

| 组件 | 责任 |
|---|---|
| `collector/watch_memory_chat.py` | 发现活跃聊天缓存区，持续以只读方式读取新的结构化聊天事件。 |
| `collector/extract_memory_chat.py` | 仅为运行时发现提供缓存区命中计数，不持久化聊天正文或内存地址。 |
| `collector/chat_event_codec.py` | 解析内部事件结构并生成稳定的 `event_id`。 |
| `archive/retention.py` | 统一排除招募频道和客户端招募卡。 |
| `archive/sqlite_store.py` | JSONL 完整行导入、SQLite schema、去重和灾后重建。 |
| `web/server.py` | 只读 HTTP API 和静态网页。 |
| `cli.py` | 安装后的统一命令入口。 |

## 数据原则

- **JSONL 是恢复源**：它保留按时间追加的输入事件，分段可以跨设备带走。
- **SQLite 是查询层**：可从所有 JSONL 重新生成，不应成为唯一备份。
- **`event_id` 是去重键**：重复导入、崩溃后的重放和多段重建不会产生重复行。
- **默认最小化输出**：内存地址、完整位置序列等诊断数据默认不进入 JSONL。

## 本地优先

默认网页只绑定 `127.0.0.1`。程序不带云同步、账号体系、网页密码、Tunnel Token、计划任务或后台遥测。任何公网访问都应由部署者在项目外部单独配置。
