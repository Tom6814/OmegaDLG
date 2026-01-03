#!/usr/bin/env python3

import os
import re
import argparse
import requests
import threading
from time import sleep
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import img2pdf
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Rich styling ---
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
    ProgressColumn,
)
from rich.theme import Theme

console = Console(
    theme=Theme(
        {
            "ok": "bold green",
            "warn": "bold yellow",
            "err": "bold red",
            "info": "cyan",
            "title": "bold magenta",
        }
    )
)


# -------------------------
# Rich Setup
# -------------------------
def _human_bytes(n: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{int(n)} {units[i]}" if i == 0 else f"{n:.1f} {units[i]}"


class ByteSizeColumn(ProgressColumn):
    """Render completed / total in human-readable bytes."""

    def render(self, task) -> Text:
        completed = _human_bytes(task.completed or 0)
        if task.total is not None:
            total = _human_bytes(task.total)
            return Text(f"{completed}/{total}")
        return Text(completed)


class SpeedColumn(ProgressColumn):
    """Render transfer speed in human-readable bytes per second."""

    def render(self, task) -> Text:
        spd = task.speed or 0.0
        return Text(f"{_human_bytes(spd)}/s")


# -------------------------
# Networking helpers
# -------------------------
def make_session():
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        }
    )
    return s


def get_with_retries(session, url, *, retries=3, timeout=20):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout, stream=True)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_err = e
            sleep(0.6 * attempt)
    raise last_err


# thread-local sessions (requests.Session is not guaranteed thread-safe)
_thread_local = threading.local()


def thread_session():
    sess = getattr(_thread_local, "session", None)
    if sess is None:
        sess = make_session()
        _thread_local.session = sess
    return sess


# -------------------------
# Series helpers
# -------------------------
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9 _-]+")


def sanitize_name(s):
    return SAFE_NAME_RE.sub("_", s).strip() or "series"


def derive_series_name(any_url, override=None):
    if override:
        return sanitize_name(override)
    path = urlparse(any_url).path.rstrip("/")
    name = path.split("/")[-1] or "series"
    return sanitize_name(name)


def ensure_series_dirs(root):
    os.makedirs(os.path.join(root, "Images"), exist_ok=True)
    os.makedirs(os.path.join(root, "Chapters"), exist_ok=True)


def chapter_label_from_url(chapter_url):
    m = re.search(
        r"(?:^|/)(?:chapter|chap|ch)[-_/]?(\d+)(?:/|$)",
        chapter_url,
        flags=re.IGNORECASE,
    )
    return m.group(1) if m else None


def chapter_dir(root, label):
    return os.path.join(root, "Images", f"chapter-{label}")


def chapter_pdf(root, label):
    return os.path.join(root, "Chapters", f"chapter-{label}.pdf")


# -------------------------
# Scraping / parsing
# -------------------------
def get_total_chapters(session, url):
    try:
        with console.status(f"[info]Fetching series page[/info] {url}"):
            response = get_with_retries(session, url)
    except requests.RequestException as e:
        console.print(f"[err]Error fetching page:[/err] {e}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    for div in soup.find_all("div", class_="flex justify-between"):
        spans = div.find_all("span")
        if len(spans) >= 2 and "Total chapters" in spans[0].get_text(strip=True):
            try:
                return int(spans[1].get_text(strip=True))
            except ValueError:
                pass
    return None


def generate_chapter_urls(base_url, total_chapters):
    base = base_url.rstrip("/")
    return [f"{base}/chapter-{i}" for i in range(1, total_chapters + 1)]


def extract_chapter_images(session, chapter_url):
    try:
        with console.status(f"[info]Loading chapter[/info] {chapter_url}"):
            response = get_with_retries(session, chapter_url)
    except requests.RequestException as e:
        console.print(f"[err]Error fetching chapter:[/err] {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    content_div = soup.find("div", id="content")
    if not content_div:
        console.print(f"[warn]No content div found:[/warn] {chapter_url}")
        return []

    image_urls = []
    for img in content_div.find_all("img"):
        src = (img.get("data-src") or img.get("src") or "").strip()
        if not src:
            continue
        # ✅ ONLY accept absolute http(s) URLs; skip paths like /icon.png or images/001.jpg
        if src.lower().startswith(("http://", "https://")):
            image_urls.append(src)
    return image_urls


# -------------------------
# PDF layout
# -------------------------
def layout_fun_fixed_width(imgwidthpx, imgheightpx, ndpi):
    page_width_pt = 720  # 10 inches
    dpi_x = ndpi[0] if ndpi and ndpi[0] and ndpi[0] > 0 else 96
    dpi_y = ndpi[1] if ndpi and ndpi[1] and ndpi[1] > 0 else 96
    img_w_in = imgwidthpx / dpi_x
    img_h_in = imgheightpx / dpi_y
    img_w_pt = img_w_in * 72
    img_h_pt = img_h_in * 72
    scale = page_width_pt / img_w_pt if img_w_pt else 1.0
    scaled_h_pt = img_h_pt * scale
    return page_width_pt, scaled_h_pt, page_width_pt, scaled_h_pt


def images_to_pdf(image_folder, output_pdf):
    src_files = sorted(
        os.path.join(image_folder, f)
        for f in os.listdir(image_folder)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    )
    if not src_files:
        console.print(f"[warn]No images in[/warn] {image_folder} — skipping PDF.")
        return False
    convert_dir = os.path.join(image_folder, "_converted")
    os.makedirs(convert_dir, exist_ok=True)
    out_files = []
    for p in src_files:
        ext = os.path.splitext(p)[1].lower()
        if ext in (".jpg", ".jpeg", ".png"):
            out_files.append(p)
            continue
        try:
            with Image.open(p) as im:
                if im.mode in ("RGBA", "LA"):
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im.convert("RGBA"), mask=im.getchannel("A"))
                    im = bg
                else:
                    im = im.convert("RGB")
                base = os.path.splitext(os.path.basename(p))[0]
                dest = os.path.join(convert_dir, base + ".jpg")
                im.save(dest, format="JPEG", quality=95)
                out_files.append(dest)
        except Exception:
            continue
    if not out_files:
        console.print(f"[warn]No convertible images in[/warn] {image_folder} — skipping PDF.")
        return False
    with console.status(f"[info]Building PDF[/info] → {output_pdf}"):
        with open(output_pdf, "wb") as f:
            f.write(
                img2pdf.convert(
                    out_files,
                    layout_fun=layout_fun_fixed_width,
                    x=None,
                    y=None,
                    border=0,
                    fit=None,
                )
            )
    console.print(f"[ok]PDF saved[/ok] {output_pdf}")
    return True


# -------------------------
# Multithreaded download utils
# -------------------------
def _is_valid_image_url(u: str) -> bool:
    parsed = urlparse(u)
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    # optional: ignore obvious non-page assets
    if parsed.path.lower().endswith((".svg", ".ico")):
        return False
    return True


def _head_content_length(url: str, timeout=10) -> int:
    if not _is_valid_image_url(url):
        return 0
    sess = thread_session()
    try:
        r = sess.head(url, allow_redirects=True, timeout=timeout)
        cl = r.headers.get("content-length")
        return int(cl) if cl and cl.isdigit() else 0
    except Exception:
        return 0


def download_images_threaded(
    image_urls, out_dir, workers=6, max_retries=3, timeout=40, verbose=False
):
    os.makedirs(out_dir, exist_ok=True)

    # Precompute destination filenames to preserve order
    jobs = []
    idx = 0
    for u in image_urls:
        if not _is_valid_image_url(u):
            continue
        idx += 1
        parsed = urlparse(u)
        ext = os.path.splitext(parsed.path)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            ext = ".jpg"
        filename = f"{idx:03d}{ext}"
        dest = os.path.join(out_dir, filename)
        jobs.append((idx, u, dest))

    if verbose and jobs:
        # Show the image URL list up-front
        url_list = "\n".join(f"{i:03d}  {u}" for i, u, _ in jobs)
        console.print(Panel.fit(url_list, title="Images (extracted)", style="info"))

    # Estimate total size concurrently for proper KB/MB progress
    total_est = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for size in pool.map(_head_content_length, (u for _, u, _ in jobs)):
            total_est += size

    results = []  # collect (idx, dest, ok, bytes, error)

    # Progress bar tracks bytes, with human-readable units
    with Progress(
        TextColumn("[bold]Downloading[/bold]"),
        BarColumn(),
        ByteSizeColumn(),
        SpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("dl", total=total_est or None)

        def _wrap_download(j):
            i, url, dest = j
            ok = False
            written = 0
            err = None
            sess = thread_session()
            last_err = None
            for attempt in range(1, max_retries + 1):
                try:
                    resp = get_with_retries(sess, url, retries=1, timeout=timeout)
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=32768):
                            if not chunk:
                                continue
                            f.write(chunk)
                            written += len(chunk)
                            progress.advance(task_id, len(chunk))
                    ok = True
                    break
                except Exception as e:
                    last_err = e
                    sleep(0.6 * attempt)
            if not ok:
                err = str(last_err)
            return (i, dest, ok, written, err)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_wrap_download, j) for j in jobs]
            for fut in as_completed(futures):
                results.append(fut.result())

    # Ordered summary table (only if requested)
    if verbose and results:
        table = Table(title="Download results", show_lines=False)
        table.add_column("#", justify="right", style="title", no_wrap=True)
        table.add_column("File", overflow="fold")
        table.add_column("Size", justify="right")
        table.add_column("Status", style="ok")

        for i, dest, ok, written, err in sorted(results, key=lambda r: r[0]):
            size_str = _human_bytes(written) if written else "-"
            status = "OK" if ok else "[err]FAIL[/err]"
            if err and not ok:
                status += f" • {err}"
            table.add_row(f"{i:03d}", os.path.basename(dest), size_str, status)

        console.print(table)

    console.print(f"[ok]{len(results)} files processed[/ok] → {out_dir}")


# -------------------------
# Workflows
# -------------------------
def run_bulk(
    session,
    series_url,
    series_name=None,
    force=False,
    workers=6,
    max_retries=3,
    verbose=False,
):
    series_dir = derive_series_name(series_url, series_name)
    ensure_series_dirs(series_dir)
    console.print(
        Panel.fit(
            f"Series directory: [title]{series_dir}[/title]\n"
            f"Images → {os.path.join(series_dir, 'Images')}\n"
            f"Chapters → {os.path.join(series_dir, 'Chapters')}",
            title="Setup",
            style="info",
        )
    )

    total = get_total_chapters(session, series_url.rstrip("/"))
    if not total:
        console.print("[err]Could not determine total chapters.[/err]")
        return

    console.print(f"[info]Total chapters found:[/info] [title]{total}[/title]")
    chapter_urls = generate_chapter_urls(series_url, total)

    for idx, chapter_url in enumerate(chapter_urls, 1):
        label = str(idx)
        pdf_path = chapter_pdf(series_dir, label)
        if os.path.exists(pdf_path) and not force:
            console.print(
                f"⏭️  [warn]Chapter {label} exists[/warn] → {pdf_path} (skipping)"
            )
            continue

        console.print(
            Panel.fit(
                f"Chapter {label}\n{chapter_url}", title="Processing", style="title"
            )
        )
        images = extract_chapter_images(session, chapter_url)
        if not images:
            console.print(f"[warn]No images for chapter {label}[/warn]")
            continue

        img_dir = chapter_dir(series_dir, label)
        download_images_threaded(
            images, img_dir, workers=workers, max_retries=max_retries, verbose=verbose
        )
        images_to_pdf(img_dir, pdf_path)


def run_single(
    session,
    chapter_url,
    series_name=None,
    chapter_num=None,
    force=False,
    workers=6,
    max_retries=3,
    verbose=False,
):
    series_dir = derive_series_name(chapter_url, series_name)
    ensure_series_dirs(series_dir)

    label = chapter_num or chapter_label_from_url(chapter_url) or "custom"
    label = str(label)

    pdf_path = chapter_pdf(series_dir, label)
    if os.path.exists(pdf_path) and not force:
        console.print(f"⏭️  [warn]Chapter {label} exists[/warn] → {pdf_path} (skipping)")
        return

    console.print(
        Panel.fit(
            f"Single Chapter {label}\n{chapter_url}", title="Processing", style="title"
        )
    )
    images = extract_chapter_images(session, chapter_url)
    if not images:
        console.print("[warn]No images found for this chapter.[/warn]")
        return

    img_dir = chapter_dir(series_dir, label)
    download_images_threaded(
        images, img_dir, workers=workers, max_retries=max_retries, verbose=verbose
    )
    images_to_pdf(img_dir, pdf_path)


# -------------------------
# CLI
# -------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description="Download manga/manhwa images into Images/ and build chapter PDFs into Chapters/."
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "-s", "--series-url", help="Series URL (bulk mode: download all chapters)."
    )
    mode.add_argument(
        "-c", "--chapter-url", help="Single-chapter URL (download just this chapter)."
    )

    p.add_argument(
        "-sn",
        "--series-name",
        help="Override series directory name (default derived from URL).",
    )
    p.add_argument(
        "-cn",
        "--chapter-num",
        help="Explicit chapter number/label for single mode if URL can't be parsed.",
    )
    p.add_argument(
        "-f", "--force", action="store_true", help="Overwrite existing chapter PDFs."
    )
    p.add_argument(
        "-w",
        "--workers",
        type=int,
        default=6,
        help="Concurrent downloads (default: 6).",
    )
    p.add_argument(
        "--max-retries", type=int, default=3, help="Retries per file (default: 3)."
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print per-image URLs and a results table.",
    )
    return p.parse_args()


def main():
    args = parse_args()
    session = make_session()
    if args.series_url:
        run_bulk(
            session,
            args.series_url,
            series_name=args.series_name,
            force=args.force,
            workers=args.workers,
            max_retries=args.max_retries,
            verbose=args.verbose,
        )
    else:
        run_single(
            session,
            args.chapter_url,
            series_name=args.series_name,
            chapter_num=args.chapter_num,
            force=args.force,
            workers=args.workers,
            max_retries=args.max_retries,
            verbose=args.verbose,
        )


if __name__ == "__main__":
    main()
