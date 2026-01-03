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



### 直接运行（无需安装）



# 浏览器访问
http://127.0.0.1:8000/
```


# 输出目录结构
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
