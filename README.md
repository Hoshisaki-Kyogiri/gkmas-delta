# gkmas-delta

学园偶像大师（学園アイドルマスター）资源更新工具。常规运行时仅下载新版本中新增或变更的资源，无需重复获取完整的游戏数据。

## 使用方法

### Windows 发布包

下载 `gkmas-delta-win64.zip`（约 49 MB），解压后运行 `启动.bat`。发布包内置 Python 3.13、全部依赖、vgmstream 与 Noto 字体，解压后约 96 MB，无需另行安装 Python 或 .NET。

### 从源码运行

```bash
pip install -r requirements.txt
python -m gkmas_delta --web
```

需要 Python 3.11 及以上版本（依赖标准库 `tomllib`）。

### 网页控制台

运行 `启动.bat`（或 `gkmas-delta.bat --web`）后，程序在本机启动网页控制台，并在浏览器中打开 `http://127.0.0.1:8765/`。控制台提供以下功能：

- **概览**：显示本地版本、服务器版本及待更新内容的数量与大小；执行更新时显示各阶段进度、传输速度与日志，并支持中途取消。
- **图片**：按版本浏览抽取出的贴图。
- **音频**：列出歌曲、BGM、语音与音效，歌曲附带对应封面。mp3 可直接播放；CRI 格式的 `.acb` / `.awb` 经 vgmstream 解码为 wav 后播放，语音包会列出其中的每一条语音。
- **视频**：CRI 格式的 `.usm` 经 ffmpeg 转换为 mp4。H.264 视频直接封装，MPEG-1 视频转码为 H.264（浏览器不支持 MPEG-1）。
- **批量转换**：音频与视频既可在打开时单独转换，也可多选后批量转换。支持拖动框选、Ctrl 点选、Shift 连选及勾选框。批量转换在后台执行，进度显示于页面右下角，可随时取消。
- **剧情**：将 Resource 中的 `adv_*.txt` 按分类与角色列出，显示台词、旁白、选项及注音，并支持全文检索台词。有配音的台词可单独播放，也可从头连续播放。阅读区支持调整字号（12–28px）及切换衬线 / 无衬线字体，设置会被保存。
- **版本筛选**：音频、视频与剧情均可按版本筛选，最近一次包含该类文件的版本排在首位。版本信息取自已保存的差量清单（`manifests/`，兼容旧工具的 `DecryptedCache/`）。
- **定位文件**：图片、音频、视频与剧情均提供「在文件夹中显示」，可在资源管理器中直接定位到对应文件。
- **设置**：编辑 `config.toml` 中的常用配置项，保存时保留文件中原有的注释。

界面字体均使用随程序分发的 Noto 字体（中文界面为 Noto Sans SC，剧情为 Noto Serif JP / Noto Sans JP，等宽文本为 Noto Sans Mono），显示效果不受系统已安装字体影响，且无需联网。字体按 Unicode 范围切片，浏览器仅加载页面实际用到的部分。

关闭命令行窗口即可退出程序。控制台运行期间再次启动 `启动.bat` 时，程序仅在浏览器中重新打开已有的控制台，不会启动第二个进程。服务仅监听 `127.0.0.1`。

转换生成的音频保存在 `data/AUDIO/<语音包>/`，视频保存在 `data/VIDEO/`。控制台支持删除所选项目的转换结果，或一次性清理全部转换结果。清理范围仅限于控制台生成的文件，即能够对应到 Resource 中某个 `.acb` / `.awb` / `.usm` 的 wav 与 mp4；上述文件夹中的其他文件以及原始 Resource 均不受影响，删除后可随时重新转换。wav 文件体积较大，单个剧情语音包约为 12 MB。

### 外部工具

| 工具 | 用途 | 大小 | 获取方式 |
|---|---|---|---|
| vgmstream | 解码 `.acb` / `.awb` | 4.3 MB | 随发布包分发 |
| ffmpeg | 转换 `.usm` 视频 | 29.8 MB | 首次打开视频时，由控制台询问后下载 |

两者均从固定地址下载（vgmstream 取自其 GitHub 发布页，ffmpeg 取自 PyPI 上的 imageio-ffmpeg wheel）。下载完成后先校验 SHA-256，校验失败的文件将被丢弃且不会解压。工具安装于程序目录下的 `bin/`。从源码运行时，vgmstream 同样在首次使用时下载；若系统 PATH 中已存在 `vgmstream-cli` 或 `ffmpeg`，程序将直接使用。

### 首次运行

尚无本地记录时，需要选择以下方式之一：

- **下载最新一个版本**（推荐）：仅获取服务器最近一次更新的内容，通常为数十至数百 MB。
- **下载完整资源**：60 GB 以上，适用于需要全套素材的情况。
- **仅记录版本号**：不下载任何文件，从下一次更新开始跟踪。

此后每次运行均从上次记录的版本号继续。

## 增量更新原理

资源服务器的清单接口原生支持增量查询：请求时携带当前版本号，服务器仅返回该版本之后发生变动的条目。

| 请求 | 响应大小 | 内容 |
|---|---|---|
| 全量 `list/0` | 4.99 MB | 24709 个 Asset / 21730 个 Resource |
| 自 v44 起 | 33 KB | 185 个 Asset / 122 个 Resource |
| 自 v45 起 | 12.8 KB | 0 个 Asset / 122 个 Resource |
| 超过最新版本号 | 54 B | 空清单，附带当前最新版本号 |

最后一种请求用于查询服务器的最新版本，`--status` 与首次运行均采用此方式。

因此，本地仅需在 `data/state.json` 中记录一个版本号，无需保存历史清单。

## 命令行

发布包使用 `gkmas-delta.bat`，从源码运行时使用 `python -m gkmas_delta`，两者参数相同。不带参数时执行「检查并下载更新」，不启动网页控制台，适用于计划任务。

```
gkmas-delta.bat                        检查并下载更新
gkmas-delta.bat --web                  启动网页控制台
gkmas-delta.bat --web --port 9000      指定控制台端口，默认 8765，被占用时自动顺延
gkmas-delta.bat --web --no-browser     启动控制台但不打开浏览器
gkmas-delta.bat --status               查看本地版本、服务器版本及待更新数量
gkmas-delta.bat --latest               仅下载最新一个版本的更新内容
gkmas-delta.bat --full                 下载完整资源（约 63 GB）
gkmas-delta.bat --baseline             仅记录当前版本号，不下载
gkmas-delta.bat --force                版本号未变化时也重新处理
gkmas-delta.bat --workers 24           临时指定下载线程数
gkmas-delta.bat --no-pause             结束后不等待回车
gkmas-delta.bat --local-cache <文件>   使用从设备导出的 octocacheevai
```

`启动.bat` 供双击使用，等同于 `gkmas-delta.bat --web`。

## 配置

`config.toml` 在首次运行时生成，也可在控制台的「设置」页中修改。常用配置项如下：

- `data_dir`：数据目录，留空时使用程序目录下的 `data/`。完整下载需要 63 GB 以上的空间，系统盘空间不足时可设为其他位置，例如 `"D:/gkmas-data"`。
- `first_run`：命令行模式下首次运行的行为，可选 `"ask"`、`"latest"`、`"full"`、`"baseline"`。
- `workers`：同时下载的连接数，网络不稳定时可适当调低。
- `keep_base_copy`：额外保存一份跨版本汇总副本。默认关闭，开启后磁盘占用约增加一倍。
- `backend`：抽图后端，详见下一节。
- `app_version`：清单接口地址中的版本号（并非游戏版本号）。游戏大版本更新后若提示「服务器不认识 app_version」，需修改此项。

## 抽图后端

- `"unitypy"`（默认）：纯 Python 实现，已包含在发布包中。
- `"assetstudio"`：调用 `AssetStudioModCLI.exe`，需要安装 .NET 9 运行时。该程序不包含在本仓库中，需自行下载并放入 `AssetStudioModCLI/` 目录，或通过 `assetstudio_path` 指定路径。

两者速度相近：处理 185 个 Asset 时，AssetStudio 耗时 14–18 秒，UnityPy 在 12 线程下耗时 13 秒（单线程为 65 秒）。依赖体积方面 UnityPy 反而略大（22.7 MB 对 15.7 MB）。默认采用 UnityPy，是因为它不依赖 .NET 运行时，发布包可以解压即用。

在 v46 的 185 个 Asset 上使用 `tools/ab_extract.py` 对两者的输出进行了比对：

```
仅 AssetStudio 有：0        真实像素差异：0        尺寸不一致：0
仅舍入差(≤1/通道)：433      UnityPy 多抽出：32 个（Sprite）
唯一缺口：Lightmap-0_comp_light  AssetStudio=6 张 vs UnityPy=1 张
```

433 处差异均为块压缩解码中的 ±1 舍入误差，视觉上无法分辨。唯一的缺口为烘焙光照贴图，不属于美术资源，且 AssetStudio 导出的该贴图本身已损坏。

复现比对结果：

```bash
python tools/ab_extract.py data/gkmas/UnobfuscateAssets/46 --out ab_out
```

## 目录结构

```
gkmas-delta/
├─ 启动.bat                启动入口
├─ gkmas-delta.bat         实际入口
├─ config.toml             配置文件，首次运行时生成
├─ gkmas_delta/            程序主体
│  └─ web/                 网页控制台
├─ tools/ab_extract.py     抽图后端比对工具
├─ tools/build.py          发布包构建脚本
├─ tools/fetch_fonts.py    Noto 字体下载脚本
├─ python/                 内置解释器（仅发布包包含）
├─ bin/                    vgmstream、ffmpeg
└─ data/
   ├─ state.json           本地版本记录
   ├─ manifests/           清单（全量及各次增量）
   ├─ gkmas/Assets/        原始 Asset，以 md5 命名
   ├─ gkmas/Resource/      原始 Resource（音频、文本等）
   ├─ gkmas/UnobfuscateAssets/<版本>/<类型>/   解混淆后的 .unity3d
   ├─ IMAGE/v<版本>/       抽取出的 PNG
   │  └─ Converted/        转换后的 webp
   ├─ AUDIO/<语音包>/      控制台转换生成的 wav
   └─ VIDEO/               控制台转换生成的 mp4
```

## 构建发布包

```bash
python tools/build.py
```

该脚本从 python.org 下载嵌入式 Python 并安装依赖，确认全部模块均可导入后移除 pip 与 setuptools，再放入 vgmstream，最终生成 `build/gkmas-delta-win64.zip`。

嵌入式 Python 不含 setuptools，无法安装需要从源码编译的包，因此脚本使用 `--only-binary=:all:`，仅安装 wheel。

## 补充说明

- 存在下载失败的文件时，版本号不会推进；再次运行即可补全缺失的文件。
- 已存在的文件会校验 md5，仅在内容变化时重新下载。设置 `verify_md5 = false` 可跳过校验以加快启动，但会遗漏同名更新的文件。
- 通过 Ctrl+C 或控制台中的「取消」中断任务是安全的：未完成的文件会被丢弃并在下次运行时重新下载，已完成的文件不会重复下载。

## 致谢与上游协议

本项目基于以下项目开发，在此向原作者致谢：

| 项目 | 作者 | 协议 | 使用部分 |
|---|---|---|---|
| [gakumas-tools](https://github.com/surisuririsu/gakumas-tools) | risりす | BSD 3-Clause | 整体架构 |
| [campus](https://github.com/vertesan/campus) | vertesan | AGPL-3.0 | 资源清单（octo）的获取流程；Asset 头部解混淆算法（`gkmas_delta/deobfuscate.py` 移植自 `octo/asset.go`） |

gakumas-tools 的版权声明及许可证全文见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可证

由于本项目包含移植自 campus（AGPL-3.0）的代码，本项目以 [AGPL-3.0](LICENSE) 协议发布。分发修改后的版本或以其提供网络服务时，须以相同协议公开源代码。

## 免责声明

本项目及其开发者与官方（BNEI、QualiArts）无任何关联。

使用本工具的风险由使用者自行承担，因使用本工具及相关资源所产生的一切后果均由使用者负责。
