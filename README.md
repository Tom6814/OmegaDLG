# OmegaDL 漫画/韩漫下载器 + GUI

一个轻量的下载工具，可批量抓取系列章节图片并生成 PDF。支持命令行与图形界面，已可打包为 Windows 单文件可执行。

## 特性
- 批量整部系列或单章下载
- 自动提取图片并生成章节 PDF
- 并发下载与失败重试
- 友好的 CLI 与简洁暗色 GUI
- 可构建为单文件 `server.exe`，一键运行本地网页界面

## 环境要求
- Python `>= 3.8`
- 依赖：`rich`、`requests`、`img2pdf`、`beautifulsoup4`（安装时自动拉取）
- Windows 用户建议安装 `pipx` 以获得隔离的命令行应用

## 安装
### 推荐：pipx
```bash
pipx install git+https://github.com/thehackersbrain/omegadl.git
# 或在本地仓库目录：
pipx install .
pipx ensurepath
```

### 本地安装（不使用 pipx）
```bash
python -m pip install .
# 开发模式：
python -m pip install -e .
```

### 直接运行（无需安装）
```bash
python main.py -h
python main.py -s https://example.com/series/foo
python main.py -c https://example.com/series/foo/chapter-1
```

## 命令行用法
常用参数来自 `main.py` 的 CLI：
- `-s/--series-url` 批量下载整部
- `-c/--chapter-url` 仅下载单章
- `-sn/--series-name` 指定保存目录名（默认由 URL 派生）
- `-cn/--chapter-num` 指定单章标签（如 `30.5`）
- `-f/--force` 覆盖已存在 PDF
- `-w/--workers` 并发数（默认 6）
- `--max-retries` 每文件重试次数（默认 3）
- `-v/--verbose` 输出每张图片 URL 和结果表

示例：
```bash
# 批量整部
omegadl -s https://omegascans.org/series/i-picked-up-an-unstable-girl-from-the-junkyard

# 单章下载
omegadl -c https://omegascans.org/series/i-picked-up-an-unstable-girl-from-the-junkyard/chapter-30-5 -cn "30.5"

# 指定并发与覆盖
omegadl -s https://example.com/series/foo -w 8 -f

# 指定目录名
omegadl -s https://example.com/series/foo -sn MySeries
```

## 图形界面（源码运行）
已内置一个简洁的网页 GUI：
```bash
python -m pip install Flask requests beautifulsoup4 img2pdf rich
python webapp/server.py
# 浏览器访问
http://127.0.0.1:8000/
```

## 单文件可执行（Windows）
可将 GUI 打包为单文件 `server.exe`：
```bash
python -m pip install pyinstaller
python -m PyInstaller --onefile --add-data "webapp/index.html;webapp" webapp/server.py
# 运行
dist\server.exe
```

说明：
- 已在 `webapp/server.py` 中适配 PyInstaller 的静态资源目录（`sys._MEIPASS`）。
- 打包后启动地址为 `http://127.0.0.1:8000/`。

## 输出目录结构
执行后会在工作目录生成以下结构：
```
<系列目录>/
  Images/
    chapter-<N>/
      001.jpg 002.jpg ...
  Chapters/
    chapter-<N>.pdf
```

## 常见问题
- `500 Internal Server Error`：目标站点临时错误，稍后重试或换镜像源。
- `pipx` 命令不可用：先执行 `python -m pip install --user pipx`，再运行 `pipx ensurepath` 并重启终端。
- PDF 未生成：确认图片已抓取到 `Images/chapter-<N>/`，并检查是否有不支持的图片格式。

## 致谢
本项目用于学习与个人备份，请遵守目标网站的使用条款与版权政策。
