# 本地服务与界面接入

六页界面放在 `gkmas_delta/web/`，由项目自带的 Python 服务直接提供，不再使用 Node 代理、外部后端路径或 `start-live.ps1`。

## 运行路径

浏览器 → `127.0.0.1:8765`（`python -m gkmas_delta --web`，项目自带服务）→ 程序目录下的 `data/` 与 `config.toml`。

启动方式：

```powershell
.\启动.bat                  # 双击入口，等同于 --web
.\gkmas-delta.bat --web
python -m gkmas_delta --web
```

默认端口为 8765；端口被占用时服务会顺延，也可用 `--port 9000` 指定。同一份配置重复启动时复用已有控制台。服务只监听 `127.0.0.1`，关闭命令行窗口即退出。

## 页面与接口

| 页面 | 接口 |
| --- | --- |
| 概览 | GET `/api/ping`、`state`、`server`、`preview`；POST `run`、`cancel`；SSE `events` |
| 图片 | GET `/api/gallery`、`images`；媒体 `/data/…`；POST `/api/reveal` |
| 音频 | GET `/api/audio`；POST `decode`、`convert`；媒体 `/data/…` |
| 视频 | GET `/api/videos`；POST `video`；媒体 `/data/VIDEO/…` |
| 剧情 | GET `/api/stories`、`story`、`story-search`；POST `voice` |
| 设置 | GET/POST `/api/config` |

`gkmas_delta/web/__init__.py` 提供 `/`（六页界面）、`/data/`、`/api/*`，以及界面自身的 CSS、脚本、图片和字体。写操作仍要求 `X-Gkmas-Delta: 1` 并检查 Host，静态路径限定在 `gkmas_delta/web/` 内。

## 文件位置

- `gkmas_delta/web/index.html`、`styles.css`、`gakuen.css`、`live.css`、`type.css`、`refine.css`、`boot.js`、`live.js`、`app.js`、`assets/`：六页界面及演示模式（`?demo=1`）。演示模式用到的卡面与封面图放在 `assets/demo/`，取自游戏资源，只留在本地，不随仓库与发布包分发。
- `docs/`：设计说明、设计过程与预览截图。
- `config.toml`、`data/`：运行产物，不随仓库分发，首次运行时生成。

## 数据

仓库不含 `data/`、`config.toml`、`bin/`、`build/`、`python/`。首次启动会生成默认 `config.toml`，数据目录默认为程序目录下的 `data/`；资源在「概览」中按原项目的更新流程下载。外部工具 vgmstream / ffmpeg 在首次需要时下载到 `bin/`。

## 已验证

- `python -m py_compile` 与 `node --check` 通过。
- 临时服务（8799 端口）上，`/`、`/index.html`、全部 CSS/JS、`/assets/…` 字体与图片及 `/api/ping`、`state`、`config`、`gallery`、`audio`、`videos`、`stories` 均返回 200；`/data/` 下不存在的文件返回 404。
- 写操作缺少 `X-Gkmas-Delta` 时返回 403，带该请求头时返回任务快照。
- `/api/events` 正常返回 SSE 的 `retry` 与空闲保活。
- 无头 Chrome 渲染概览与图片页，浏览器控制台无错误；概览显示服务器版本 v70，数据目录指向程序目录下的 `data/`。

本次未执行资源下载、转换、配音解码、配置保存或工具安装；这些写操作仍按后端契约连接，需要手动触发。
