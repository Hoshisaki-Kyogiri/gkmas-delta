# umegkmas

学园偶像大师（学園アイドルマスター）资源更新工具。

和上一代工具最大的区别：**默认只下载更新，不下载整个游戏。**

## 为什么能只下更新

资源服务器的清单接口本身就支持增量。向它报告"我当前是 v45"，它只返回 v45 之后变动的条目：

| 请求 | 响应体积 | 内容 |
|---|---|---|
| 全量 | 4.99 MB | 24709 个资源包 / 21730 个文件 |
| 从 v44 起 | 33 KB | 185 个资源包 / 122 个文件 |
| 从 v45 起 | 12.8 KB | 0 个资源包 / 122 个文件 |

所以本地只需要记住一个版本号（存在 `data/state.json`），不需要保存历史清单，也不需要先下载整个游戏才能开始追更新。

## 快速开始

### 绿色包（推荐给不折腾的人）

下载 `umegkmas-green-win64.zip`（28 MB），解压，双击 `启动.bat`。

**不需要装 Python，不需要装 .NET，不需要 pip。** 解压后 69 MB，自带 Python 3.13 和全部依赖。

### 从源码运行

```bash
pip install -r requirements.txt
python -m umegkmas
```

需要 Python 3.11 以上（用到标准库 `tomllib`）。

### 第一次运行

不管用哪种方式，第一次运行都会问你：

```
  [1] 只记录当前版本，从下次更新开始增量下载  （推荐，几乎不占空间）
  [2] 下载整个游戏资源                        （15 GB 以上，很慢）
  [3] 退出
```

选 **1**，程序记下当前版本号就结束，一个文件都不下。之后每次运行只会拉取新增和变动的内容。

选 **2** 会下载完整资源库，适合需要全套素材的情况。

之后每次双击 `启动.bat` 就是「检查并下载更新」。（`启动.bat` 只是转发给 `umegkmas.bat`，后者是 ASCII 名的真正入口，避免中文名在某些环境下出问题。）

## 命令行

不加参数 = 检查并下载更新。

```
启动.bat --status      查看本地版本、服务器版本、有多少待更新
启动.bat --full        下载完整资源
启动.bat --baseline    只记录当前版本号，不下载
启动.bat --force       版本号没变也重新处理一遍
启动.bat --workers 24  临时指定下载线程数
启动.bat --no-pause    结束后不等回车（用于计划任务）
启动.bat --local-cache <文件>   改用设备上的 octocacheevai
```

## 配置

`config.toml`，首次运行自动生成。常用项：

- `data_dir` — 数据存哪。留空 = 程序目录下的 `data/`。全量下载需要 15 GB 以上，C 盘不够就填 `"D:/gkmas-data"`。
- `workers` — 同时下载的连接数，网络不好就调小。
- `keep_base_copy` — 额外写一份跨版本汇总副本。**默认关闭**，打开会让磁盘占用翻倍。
- `backend` — 抽图后端，见下。
- `app_version` — 游戏大版本号。提示"服务器不认识游戏版本"时改这里。

## 抽图后端

两个可选：

- `"unitypy"`（默认）— 纯 Python，不需要 .NET，跨平台，绿色包里已内置。
- `"assetstudio"` — 调用 `AssetStudioModCLI.exe`，需要机器上装有 **.NET 9 运行时**。仓库里不含这个程序，需要自己下载后放到程序目录下的 `AssetStudioModCLI/` 里，或在 config.toml 用 `assetstudio_path` 指定。

选 UnityPy 作默认不是因为它快 —— 实测两者基本打平（185 个资源包：AssetStudio 14~18 秒，UnityPy 12 线程 13 秒，单线程 65 秒），而且 UnityPy 依赖链 22.7 MB 比 AssetStudio 的 15.7 MB 还大 7 MB。选它是因为它**不需要 .NET 9 运行时**，这是绿色包能做到"解压双击即用"的前提。

两者在 v46 增量的 185 个资源包上做过实测比对（`tools/ab_extract.py`）：

```
仅 AssetStudio 有：0        真实像素差异：0        尺寸不一致：0
仅舍入差(≤1/通道)：433      UnityPy 多抽出：32 个（Sprite）
唯一缺口：Lightmap-0_comp_light  AssetStudio=6 张 vs UnityPy=1 张
```

433 处差异全部是块压缩解码器的 ±1 舍入，视觉无差别。唯一缺口是光照贴图（烘焙场景光照数据，非美术资源），且 AssetStudio 导出的那张 lightmap 本身就是损坏的。

自己复验：

```bash
python tools/ab_extract.py data/gkmas/UnobfuscateAssets/46 --out ab_out
```

## 目录结构

```
umegkmas/
├─ 启动.bat                双击这个
├─ config.toml             配置，首次运行生成
├─ umegkmas/               程序本体
├─ umegkmas.bat            真正的入口（ASCII 名）
├─ tools/ab_extract.py     抽图后端 A/B 比对工具
├─ tools/build_green.py    绿色包构建脚本
├─ python/                 内置解释器（仅绿色包有）
└─ data/                   所有产物
   ├─ state.json           本地版本记录
   ├─ manifests/           清单（全量 / 各次增量）
   ├─ gkmas/Assets/        原始资源包（按 md5 命名）
   ├─ gkmas/Resource/      原始文件（音频/文本等）
   ├─ gkmas/UnobfuscateAssets/<版本>/<类型>/   解混淆后的 .unity3d
   └─ IMAGE/v<版本>/       抽出的 PNG
      └─ Converted/        转换后的 webp
```

## 自己构建绿色包

```bash
python tools/build_green.py
```

从 python.org 拉嵌入式 Python，把依赖以 **wheel 形式**装进去（嵌入式发行版没有 setuptools，任何回退到源码编译的包都会失败，所以脚本强制 `--only-binary=:all:`），验证全部模块可加载，剥掉 pip/setuptools，最后打成 zip。

产出 `build/umegkmas-green-win64.zip`。

## 已知行为

- 下载失败的文件不会推进版本号，再运行一次会自动补下。
- 已存在的文件按 md5 校验，只有内容变了才重下（`verify_md5 = false` 可关掉以加快启动，但会漏掉同名更新的文件）。
- 中断（Ctrl+C）安全，未完成的文件以 `.part` 保留并在下次重下。

## 免责声明

自行承担使用风险，使用本工具及相关资源的一切后果由使用者负责。
