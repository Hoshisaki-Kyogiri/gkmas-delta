# umegkmas

学园偶像大师（学園アイドルマスター）的资源更新工具。平时只下载新版本变动的部分，不用每次拉整个游戏。

## 用法

### 绿色包

下载 `umegkmas-green-win64.zip`（28 MB），解压后双击 `启动.bat`。包里自带 Python 3.13 和依赖，解压后约 69 MB，不用另装 Python 或 .NET。

### 源码

```bash
pip install -r requirements.txt
python -m umegkmas --web
```

需要 Python 3.11+（用到 `tomllib`）。

### 网页控制台

`启动.bat` 不带参数时会在本机起一个网页控制台，并打开浏览器到 `http://127.0.0.1:8765/`。页面上有：

- 本地版本、服务器版本，以及待更新的文件数和大小
- 「检查并下载更新」按钮，运行时显示各阶段进度、速度和日志，可以中途取消
- 按版本浏览抽出来的图片
- 常用配置的编辑（保存到 `config.toml`，原有注释会保留）

关掉命令行窗口就退出了。控制台已经开着时再双击 `启动.bat`，只会重新打开浏览器，不会再起一个进程。服务只监听 `127.0.0.1`。

### 第一次运行

还没有本地记录时需要选一种方式：

- 下载最新一个版本：只取服务器最近一次更新的内容，一般几十到几百 MB。推荐这个。
- 下载整个游戏：60 GB 以上，需要全套素材时再选。
- 只记下版本号：什么都不下，从下一次更新开始追。

之后每次运行都从上次记录的版本号继续。

## 增量是怎么做的

资源服务器的清单接口本身支持增量：请求时带上当前版本号，服务器只返回之后变动的条目。

| 请求 | 响应大小 | 内容 |
|---|---|---|
| 全量 `list/0` | 4.99 MB | 24709 个资源包 / 21730 个文件 |
| 从 v44 起 | 33 KB | 185 个资源包 / 122 个文件 |
| 从 v45 起 | 12.8 KB | 0 个资源包 / 122 个文件 |
| 超过最新版本号 | 54 B | 空清单，附带当前最新版本号 |

最后一种用来查询服务器最新版本，`--status` 和首次运行都用它。

所以本地只需要在 `data/state.json` 里记一个版本号，不用保存历史清单。

## 命令行

`umegkmas.bat` 不带参数就是「检查并下载更新」，不开网页，可以用在计划任务里。`启动.bat` 带参数时也走命令行。

```
启动.bat --web                打开网页控制台（启动.bat 不带参数时就是这个）
启动.bat --web --port 9000    指定端口，默认 8765，被占用会往后找
启动.bat --web --no-browser   不自动打开浏览器
启动.bat --status             查看本地版本、服务器版本和待更新数量
启动.bat --latest             只下载最新一个版本的更新内容
启动.bat --full               下载完整资源（约 63 GB）
启动.bat --baseline           只记录当前版本号，不下载
启动.bat --force              版本号没变也重新处理一遍
启动.bat --workers 24         临时指定下载线程数
启动.bat --no-pause           结束后不等回车
启动.bat --local-cache <文件>  使用从设备上拷出来的 octocacheevai
```

`启动.bat` 只是转发给 `umegkmas.bat`，用 ASCII 文件名做真正的入口，是为了避开某些环境下中文文件名的问题。

## 配置

`config.toml` 在第一次运行时生成，也可以在控制台的设置页里改。常用的几项：

- `data_dir`：数据目录，留空就是程序目录下的 `data/`。全量下载要 63 GB 以上，C 盘放不下可以填 `"D:/gkmas-data"` 之类。
- `first_run`：命令行模式下首次运行怎么办，可选 `"ask"`、`"latest"`、`"full"`、`"baseline"`。
- `workers`：同时下载的连接数，网络不稳就调小。
- `keep_base_copy`：额外保存一份跨版本汇总副本，默认关，打开后磁盘占用翻倍。
- `backend`：抽图后端，见下节。
- `app_version`：游戏大版本号。提示「服务器不认识游戏版本」时改这里。

## 抽图后端

- `"unitypy"`（默认）：纯 Python，绿色包里已经带了。
- `"assetstudio"`：调用 `AssetStudioModCLI.exe`，需要装 .NET 9 运行时。程序本身不在仓库里，要自己下载放到 `AssetStudioModCLI/` 目录，或者用 `assetstudio_path` 指定路径。

两者速度差不多：185 个资源包，AssetStudio 14~18 秒，UnityPy 开 12 线程 13 秒（单线程 65 秒）。依赖体积上 UnityPy 反而大一些（22.7 MB 对 15.7 MB）。默认用 UnityPy，是因为它不需要 .NET 运行时，绿色包才能解压直接用。

在 v46 的 185 个资源包上用 `tools/ab_extract.py` 对比过两者的输出：

```
仅 AssetStudio 有：0        真实像素差异：0        尺寸不一致：0
仅舍入差(≤1/通道)：433      UnityPy 多抽出：32 个（Sprite）
唯一缺口：Lightmap-0_comp_light  AssetStudio=6 张 vs UnityPy=1 张
```

433 处差异都是块压缩解码的 ±1 舍入，看不出区别。唯一的缺口是烘焙光照贴图，不是美术资源，而且 AssetStudio 导出的那张本身就是坏的。

想自己验证：

```bash
python tools/ab_extract.py data/gkmas/UnobfuscateAssets/46 --out ab_out
```

## 目录结构

```
umegkmas/
├─ 启动.bat                双击这个
├─ umegkmas.bat            实际入口
├─ config.toml             配置，首次运行生成
├─ umegkmas/               程序
│  └─ web/                 网页控制台
├─ tools/ab_extract.py     抽图后端对比
├─ tools/build_green.py    构建绿色包
├─ python/                 内置解释器（只有绿色包有）
└─ data/
   ├─ state.json           本地版本记录
   ├─ manifests/           清单（全量和各次增量）
   ├─ gkmas/Assets/        原始资源包，按 md5 命名
   ├─ gkmas/Resource/      原始文件（音频、文本等）
   ├─ gkmas/UnobfuscateAssets/<版本>/<类型>/   解混淆后的 .unity3d
   └─ IMAGE/v<版本>/       抽出的 PNG
      └─ Converted/        转换后的 webp
```

## 构建绿色包

```bash
python tools/build_green.py
```

脚本从 python.org 下载嵌入式 Python，把依赖装进去，检查模块都能导入，删掉 pip 和 setuptools，最后打包成 `build/umegkmas-green-win64.zip`。

嵌入式 Python 没有 setuptools，需要从源码编译的包装不上，所以脚本加了 `--only-binary=:all:`，只装 wheel。

## 其他说明

- 有文件下载失败时，版本号不会前进，再运行一次会补下。
- 已存在的文件会校验 md5，内容变了才重下。`verify_md5 = false` 可以跳过校验、启动快一些，但同名更新的文件会被漏掉。
- 中途按 Ctrl+C 或在控制台点取消都没问题：没下完的文件会丢掉下次重下，已经下完的不会重下。

## 免责声明

使用风险自负，使用本工具及相关资源产生的一切后果由使用者自己承担。
