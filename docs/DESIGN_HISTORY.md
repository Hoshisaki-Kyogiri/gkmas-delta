# gkmas-delta UI 设计记录

六页界面最初作为独立前端原型制作，现已并入本仓库的 `gkmas_delta/web/`，由内置 Python 服务直接提供（运行方式见根目录 README）。以下保留设计过程与验证记录。早期原型不改原项目源码，也不调用游戏资源或项目 API。

## 预览

早期原型使用本地静态服务（`npm run dev`，访问 4173 或 14713 端口）。并入后端后不再需要独立服务，运行 `python -m gkmas_delta --web` 即可在 8765 端口查看界面。

右上角切换 **学园**、**Swiss** 与 **Editorial**。默认“学园”方向参考官网白底、细线框和对角圆角，并保留资源工具的信息架构。六个页面通过左侧导航进入，小屏改为顶部导航。参考分析见 [OFFICIAL_REFERENCE.md](OFFICIAL_REFERENCE.md)。

- Swiss：冷白背景、无衬线字体、细线网格、编号导航、原项目紫色强调，偏工作台。
- Editorial：暖灰背景、衬线标题、同一紫色强调、加大的素材面积，偏阅读与浏览。

两种排版共用原项目主色 `#706CAA`。搭配与文案修改说明见 [DESIGN.md](DESIGN.md)。页面文案使用功能名称、数量、状态和操作说明。

## 可体验的交互

概览中的更新模拟与取消、重置；图片分类、角色、版本、搜索、列表/网格、详情弹窗；音频类别、搜索、选择与批量转换反馈、播放动效；视频搜索与详情；剧情搜索（包括台词）、篇章切换、字号与字体；浏览器本地设置保存。

版本、统计、下载进度、音视频列表均为演示数据。播放按钮只演示动效，不包含实际音频或视频。剧情台词为原创示例，不来自游戏原文。素材的版本分组是展示用分类，不代表真实发布时间。logo 使用原项目的 Quicksand，界面使用 Noto Sans SC，字体均从本地静态文件加载，无外部字体请求。

## 素材来源

从本机 `E:/openGakumas/IMAGE/` 复制六张已有游戏素材到 `gkmas_delta/web/assets/`，保持原图，不修改原文件。用途仅为本地界面演示；游戏美术归相应权利方。

原项目的猪图标及 Quicksand、Noto Sans SC 字体沿用至 `gkmas_delta/web/assets/`，图标为 `assets/logo.webp`；字体文件及 SIL Open Font License 保留在 `assets/fonts/`。

| 本地文件 | 原素材文件名 |
| --- | --- |
| saki.png | img_general_cidol-hski-3-000_0-full.png |
| temari.png | img_general_cidol-ttmr-3-000_0-full.png |
| kotone.png | img_general_cidol-fktn-3-000_0-full.png |
| support.png | img_general_csprt-3-0000_full.png |
| sumika.png | img_adv_still_dear_shro_003-00.png |
| album.png | img_general_music_jacket_all-shro-016.png |

`server.cjs` 是早期原型的静态服务；并入后该文件已移除，静态文件改由 `gkmas_delta/web/__init__.py` 提供。

## 验证记录

2026-10-12：JavaScript 语法检查通过，静态服务返回 HTTP 200。浏览器验证了更新完成与重置、两种风格切换、图片分类/搜索/详情、音频全选/批量操作反馈/播放动效、视频列表、剧情台词搜索/篇章切换/字号调整、预览设置保存。桌面与 390px 窄屏布局已检查，窄屏音频横向溢出已修复；未发现浏览器脚本错误。

首版截图在 `previews/`：`swiss-overview.jpg`、`editorial-overview.jpg`、`editorial-story.jpg`、`mobile-overview.jpg`。

紫色修订版截图：`purple-swiss-overview.jpg`、`purple-editorial-overview.jpg`。已核对原主色 `#706CAA`、三条批注的文案修改、素材加载、音频与设置页标题以及 390px 概览无横向溢出；未发现浏览器脚本错误。

随后按信息系统原则重排概览，更新任务优先，资源入口与文件列表其次；移除精选卡面、装饰编号、重复的中英标签和无必要副标题。播放器改为紧凑操作区。

信息系统版已验证更新取消、资源入口跳转、紧凑播放器交互以及视频详情对应的视频文件名和大小。390px 窄屏下页面无横向溢出，文件表格在容器内滚动；未发现浏览器脚本错误。截图为 `previews/information-overview.jpg`。

当时的独立预览使用 http://localhost:14713/ （原 4173 端口被系统拒绝绑定）；并入后端后不再需要该端口，也不再需要 `DELTA_PREVIEW_PORT` 环境变量。

后续修订：删除概览的图片文件表，恢复原猪图标，采用较柔和的字体与字重；图片缩略图为约 184×138px，视频约 184×104px，点击仍可打开详情。已验证字体加载、大图详情及 390px 两页无横向溢出；浏览器无脚本错误。截图为 `previews/soft-overview.jpg`、`previews/soft-images.jpg`、`previews/soft-video.jpg`。

2026-10-13：直接查看官网首页与 Media 资料页后，新增独立的 `gakuen.css` 样式。主内容白底、紫色细线框、对角圆角，以及六个功能对应的细线图标；原项目猪图标、紫色主色、小图尺寸、操作路径与数据层级保留。不调用官网资源，也未复制官网 CSS、脚本或文案。

“学园”方案验证：1277px 桌面下素材筛选、列表切换、详情与更新取消正常；390px 下六页无横向溢出，视频縮略图仍保持紧凑；浏览器无脚本错误。截图为 `previews/gakuen-images-desktop.jpg`、`previews/gakuen-overview-desktop.jpg`、`previews/gakuen-images-mobile.jpg`。

批注修订：日志正文改为 13px Noto Sans SC，时间为 12px 等宽字体。所有预览图片、视频封面、音频封面与列表缩略图使用原比例完整显示，在固定框中留白，不再裁切或悬停放大。已核对日志实际字体/字号及各页的 `contain` 显示规则，浏览器无脚本错误；截图为 `previews/readable-log.jpg` 和 `previews/original-ratio-images.jpg`。
