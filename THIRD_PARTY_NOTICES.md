# Third-party notices

gkmas-delta 包含或改编了以下项目的代码，或随发布包分发、按需下载以下项目的程序。

## gakumas-tools

来源：https://github.com/surisuririsu/gakumas-tools

```
BSD 3-Clause License

Copyright (c) 2024-2026, risりす

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## campus

来源：https://github.com/vertesan/campus

协议：GNU Affero General Public License v3.0（AGPL-3.0），全文见 https://www.gnu.org/licenses/agpl-3.0.txt

`gkmas_delta/deobfuscate.py` 中的 Asset 头部解混淆算法移植自 campus 的 `octo/asset.go`。

## vgmstream

来源：https://github.com/vgmstream/vgmstream （r2117，Windows 版本随发布包分发，位于 `bin/vgmstream/`）

用于解码 CRI 格式的 `.acb` / `.awb` 音频。其附带的 DLL 包含 FFmpeg、mpg123、libvorbis 等组件，各组件的许可条款见相应项目的说明。

```
Copyright (c) 2008-2025 Adam Gashlin, Fastelbja, Ronny Elfert, bnnm,
                        Christopher Snowhill, NicknineTheEagle, bxaimc,
                        Thealexbarney, CyberBotX, EdnessP, et al

Portions Copyright (c) 2004-2008, Marko Kreen
Portions Copyright 2001-2007  jagarl / Kazunori Ueno <jagarl@creator.club.ne.jp>
Portions Copyright (c) 1998, Justin Frankel/Nullsoft Inc.
Portions Copyright (C) 2006 Nullsoft, Inc.
Portions Copyright (c) 2005-2007 Paul Hsieh
Portions Copyright (C) 2000-2004 Leshade Entis, Entis-soft.
Portions Public Domain originating with Sun Microsystems

Permission to use, copy, modify, and distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

## FFmpeg

来源：https://ffmpeg.org/ ，二进制取自 imageio-ffmpeg 0.6.0 的 Windows wheel（https://pypi.org/project/imageio-ffmpeg/ ）

用于将 CRI 格式的 `.usm` 视频转换为 mp4。该程序不随发布包分发，仅在首次通过控制台打开视频时下载至 `bin/ffmpeg/`。此构建包含 libx264，以 GPL 协议发布，源代码见 https://ffmpeg.org/download.html 。

## Noto 与 Quicksand 字体

来源：Google Noto Fonts 与 Quicksand（The Quicksand Project Authors），均采用 Fontsource 5.3.0 的可变字重版本（https://fontsource.org/ ），位于 `gkmas_delta/web/fonts/`，由 `tools/fetch_fonts.py` 生成。

包括 Noto Sans SC、Noto Sans JP、Noto Serif JP、Noto Sans Mono 与 Quicksand，以 SIL Open Font License 1.1 协议分发，许可证全文见各字体文件夹中的 `LICENSE`。
