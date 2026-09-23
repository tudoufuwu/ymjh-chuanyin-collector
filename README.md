# 一梦江湖传音采集

> Windows 本地聊天采集、JSONL 归档、SQLite 去重与网页查询工具。

**一梦江湖传音采集**是一个本地优先的个人归档项目：在你有权访问的 Windows 游戏进程上以只读方式读取结构化聊天事件，写入 JSONL，再同步到 SQLite 并在本机网页中查询。默认网页仅监听 `127.0.0.1:8766`，不会自动配置公网地址、Tunnel、账号或密码。

## 重要边界

- 只对你拥有或明确获授权检查的软件和数据使用采集器。
- 采集器只请求 Windows 的进程查询与读取权限；它不写入目标进程、不注入代码、不修改内存保护、不处理账号或网络会话。
- **绝不要提交**真实聊天、SQLite、JSONL、截图、日志、抓包、内存转储、密码、Token、域名、Tunnel ID 或本机配置。
- `var/` 是所有本地运行数据的位置，已被 `.gitignore` 排除。
- 项目源码采用 [GPL-3.0](./LICENSE)。这不授予任何游戏资源、聊天内容、账号数据或第三方资料的再分发权。

## 功能

```text
授权的 Windows 进程
  → 只读结构化聊天采集
  → var/raw/*.jsonl
  → SQLite 幂等归档
  → http://127.0.0.1:8766 本地网页
```

- Windows x64、Python 3.11+ 的只读聊天采集器；
- JSONL 原始归档与按大小轮转；
- SQLite 唯一 `event_id` 去重，重复导入不重复写入；
- 从全部 JSONL 分段重建 SQLite，适合灾后恢复；
- 按频道、日期、正文、角色名和角色 ID 查询的本地网页；
- 合成样例和离线单元测试，不包含任何真实数据；
- 默认只使用 Python 标准库，没有运行时第三方依赖。

## 快速开始

在 PowerShell 中：

```powershell
# 1. 克隆后进入项目目录
cd .\ymjh-chuanyin-collector

# 2. 创建虚拟环境并以可编辑模式安装
.\scripts\setup.ps1

# 3. 导入合成演示数据（不会访问游戏）
.\.venv\Scripts\python.exe -m ymjh_chuanyin demo --root .

# 4. 打开本地网页
.\.venv\Scripts\python.exe -m ymjh_chuanyin serve --root .
```

浏览器打开 <http://127.0.0.1:8766>。

完整说明见：

- [安装说明](./docs/installation.md)
- [新设备恢复指南](./docs/recovery.md)
- [架构说明](./docs/architecture.md)
- [输入 JSONL 格式](./docs/input-format.md)
- [隐私与保留政策](./docs/privacy-and-retention.md)
- [公网绑定与安全使用](./docs/responsible-use.md)

## 正常采集启动

确认游戏已经启动且已进入角色后，可先查找 PID：

```powershell
Get-Process wyclx64 | Select-Object Id, ProcessName
```

然后运行：

```powershell
.\.venv\Scripts\python.exe -m ymjh_chuanyin capture --root . --pid <PID> --quiet
```

另开两个 PowerShell 窗口分别运行入库和网页：

```powershell
.\.venv\Scripts\python.exe -m ymjh_chuanyin import --root . --follow
.\.venv\Scripts\python.exe -m ymjh_chuanyin serve --root .
```

也可以让 `scripts\start-local.ps1` 一次启动三项服务：

```powershell
.\scripts\start-local.ps1 -GamePid <PID>
```

它只写入 `var/`，不会停止旧项目的进程、不创建计划任务，也不会配置公网 Tunnel。停止这组新服务时使用：

```powershell
.\scripts\stop-local.ps1
```

> 默认不写入内存地址或完整序列字段。仅在你确实需要本机诊断时，才显式添加 `--diagnostic-addresses` 或 `--diagnostic-serial-values`；这些输出更敏感，不应公开、上传或分享。

## 恢复已有归档

真实 JSONL 和 SQLite 不在 GitHub 仓库中。请单独加密备份你自己的原始 JSONL。恢复时：

```powershell
# 将自己保存的 *.jsonl 放入 var\raw\ 后
.\.venv\Scripts\python.exe -m ymjh_chuanyin rebuild --root . --replace
.\.venv\Scripts\python.exe -m ymjh_chuanyin serve --root .
```

详细流程见 [恢复指南](./docs/recovery.md)。

## 自己的公网地址 / Tunnel

本项目不写死任何域名、Tunnel ID 或 Token。网页保持 `127.0.0.1:8766` 监听即可由你自己的反向代理或 Tunnel 转发。请先阅读 [公网绑定与安全使用](./docs/responsible-use.md)：网页没有内置公网认证，直接暴露真实聊天记录是不安全的。

## 不包含的内容

初始公开版不会提交任何真实数据、个人配置、官方游戏图像资源、抓包、账号/会话材料、第三方二进制、角色面板自动化、Frida/Hook、RC4、会话接续、协议重放或其它不属于日常采集/归档/查询链路的研究工具。

## 开发

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试只使用临时目录和合成数据。贡献前请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md) 与 [SECURITY.md](./SECURITY.md)。
