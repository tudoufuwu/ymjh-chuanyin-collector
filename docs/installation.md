# 安装说明

## 环境要求

- 64 位 Windows 10/11；
- 64 位 Python **3.11 或更高版本**，安装时勾选可从命令行使用 Python；
- 浏览器；
- 若使用实际采集：已经启动且你有权检查的目标程序。

运行归档、导入、重建和网页不需要第三方 Python 包。采集器调用 Windows 的只读进程 API，因此不支持 Linux 或 macOS。

## 从 GitHub 安装

```powershell
git clone https://github.com/tudoufuwu/ymjh-chuanyin-collector.git
cd ymjh-chuanyin-collector
.\scripts\setup.ps1
```

`setup.ps1` 只在项目目录创建 `.venv` 并安装当前项目；它不安装游戏、Tunnel、计划任务或系统服务。

如果机器上 `python` 不可用，请先安装 Python 3.11+，重新打开 PowerShell 后再执行脚本。

## 验证安装（不访问游戏）

```powershell
.\.venv\Scripts\python.exe -m ymjh_chuanyin demo --root .
.\.venv\Scripts\python.exe -m ymjh_chuanyin serve --root .
```

浏览器访问 <http://127.0.0.1:8766>。完成后按 `Ctrl+C` 停止网页服务。

## 日常运行目录

```text
var/
├─ raw/       # 本地 JSONL 原始归档
├─ archive/   # SQLite 查询数据库
├─ logs/      # 新启动脚本的本地日志
└─ run/       # 新启动脚本的临时状态
```

整个 `var/` 都被忽略，不能提交到 Git。

## 手工启动顺序

1. 找到目标程序 PID：

   ```powershell
   Get-Process wyclx64 | Select-Object Id, ProcessName
   ```

2. 启动只读采集器：

   ```powershell
   .\.venv\Scripts\python.exe -m ymjh_chuanyin capture --root . --pid <PID> --quiet
   ```

3. 在另一窗口启动持续入库：

   ```powershell
   .\.venv\Scripts\python.exe -m ymjh_chuanyin import --root . --follow
   ```

4. 在第三窗口启动网页：

   ```powershell
   .\.venv\Scripts\python.exe -m ymjh_chuanyin serve --root .
   ```

可以用 `scripts\start-local.ps1 -GamePid <PID>` 代替后三步的服务启动。它会记录自己的 PID 到 `var\run\services.json`，使用 `scripts\stop-local.ps1` 停止这组服务。

## 常用命令

| 命令 | 作用 |
|---|---|
| `init --root .` | 创建本地运行目录。 |
| `capture --root . --pid <PID>` | 只读采集新聊天并写入 JSONL。 |
| `import --root . --follow` | 跟随 JSONL 并持续写入 SQLite。 |
| `rebuild --root . --replace` | 从 `var/raw/` 的 JSONL 分段重新创建 SQLite。 |
| `serve --root .` | 启动本地查询网页。 |
| `demo --root .` | 导入合成演示数据。 |
| `status --root .` | 显示本地路径和数据库是否存在。 |

## 文件轮转

采集器默认在活动 JSONL 达到 512 MB 时创建带时间戳的新分段。入库器只持续跟随当前活动文件；轮转后，请重新启动持续入库进程，或执行 `rebuild` 从所有 JSONL 分段生成新的 SQLite。不要删除 JSONL，除非你已确认自己的备份策略。
