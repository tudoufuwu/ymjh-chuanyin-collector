# JSONL 输入格式

`var/raw/` 内的每个 `.jsonl` 文件都由一行一个 JSON 对象组成。最小事件格式见 [`schema/raw-chat-event.schema.json`](../schema/raw-chat-event.schema.json)。

## 最小示例

```json
{
  "event_id": "unique-event-id",
  "time": "2026-01-01T10:00:00+08:00",
  "channel": "xitong",
  "role_id": "example-role-id",
  "role_name": "示例角色",
  "text": "示例传音",
  "source": "authorized-local-collector"
}
```

必填字段：

| 字段 | 含义 |
|---|---|
| `event_id` | 稳定且全局唯一的事件标识，用于 SQLite 去重。 |
| `time` | 服务端或事件时间，ISO 8601 格式。 |
| `channel` | 原始频道标识，例如 `world`、`xitong`、`school`。 |
| `text` | 聊天正文。 |
| `source` | 采集来源说明。 |

常用可选字段：`observed_time`、`subchannel`、`role_id`、`role_name`、`level`、`message_kind_code`、`event_type_code`、`route_code`。

## 频道归类

- `world` + `world_all_server`：互联世界；
- `world` + 其他子频道：世界；
- `xitong` 且同时有角色名和角色 ID：传音；
- `zhaomu` / `recruit`：默认不入库；
- `season` + `message_kind_code = 1044`：默认视为客户端招募卡并不入库；
- 未识别频道：保留原字段，归为“其他”。

## 适配器要求

如果你自己拥有另一个有授权的采集来源，它可以直接向 JSONL 输出这种格式，然后使用：

```powershell
.\.venv\Scripts\python.exe -m ymjh_chuanyin import --root . --input <你的文件.jsonl>
```

不要把地址、内存内容、网络帧、密码、Cookie、Token 或完整协议序列作为常规 JSONL 字段。若本机诊断确实需要此类资料，应保存在不受 Git 跟踪的加密目录中，并在结束后按自己的数据保留政策处理。
