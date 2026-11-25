#!/usr/bin/env python3
"""Build and validate the 72-font catalog from official Google Fonts assets."""
from __future__ import annotations
import argparse, json, re, shutil, sys, urllib.parse, urllib.request, zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
GOOGLE_FONTS = "https://raw.githubusercontent.com/google/fonts/main"
SPECIMEN = "The quick brown fox 0123456789"
CATEGORIES = [
    ("sans-serif", ["Inter", "Roboto", "Open Sans", "Lato", "Montserrat", "Source Sans 3"]),
    ("serif", ["Merriweather", "Playfair Display", "Lora", "Libre Baskerville", "Cormorant Garamond", "Source Serif 4"]),
    ("slab-serif", ["Arvo", "Bitter", "Zilla Slab", "Bree Serif", "Rokkitt", "Josefin Slab"]),
    ("script", ["Dancing Script", "Great Vibes", "Pacifico", "Allura", "Sacramento", "Marck Script"]),
    ("handwritten", ["Caveat", "Patrick Hand", "Kalam", "Indie Flower", "Architects Daughter", "Shadows Into Light"]),
    ("display", ["Bebas Neue", "Oswald", "Anton", "Abril Fatface", "Bungee", "Staatliches"]),
    ("geometric", ["Poppins", "Raleway", "Josefin Sans", "Outfit", "Manrope", "Urbanist"]),
    ("monospace", ["Roboto Mono", "Space Mono", "Source Code Pro", "IBM Plex Mono", "Inconsolata", "Fira Code"]),
    ("blackletter", ["UnifrakturCook", "UnifrakturMaguntia", "Pirata One", "Germania One", "Grenze Gotisch", "MedievalSharp"]),
    ("stencil", ["Stardos Stencil", "Saira Stencil One", "Allerta Stencil", "Graduate", "Big Shoulders Stencil Display", "Black Ops One"]),
    ("rounded", ["Nunito", "Quicksand", "Varela Round", "Comfortaa", "Baloo 2", "Dosis"]),
    ("decorative", ["Lobster", "Righteous", "Fredoka", "Bungee Shade", "Bowlby One SC", "Yeseva One"]),
]
ALLOWED_LICENSES = {"OFL", "APACHE2", "UFL"}
CATALOG_ITEMS = [(cat, family) for cat, families in CATEGORIES for family in families]
CATALOG_INDEX = {item: index for index, item in enumerate(CATALOG_ITEMS)}

def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())

def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "FontCatalogPackBuilder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()

def fetch_metadata(family: str) -> tuple[str, str, str]:
    slug = slugify(family)
    url = f"{GOOGLE_FONTS}/ofl/{slug}/METADATA.pb"
    try:
        raw = fetch_bytes(url).decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"{family}: could not retrieve official metadata at {url}: {exc}") from exc
    name_match = re.search(r'^name:\s*"([^"]+)"', raw, re.MULTILINE)
    license_match = re.search(r'^license:\s*"([^"]+)"', raw, re.MULTILINE)
    if not name_match or name_match.group(1) != family:
        raise RuntimeError(f"{family}: metadata family mismatch ({name_match.group(1) if name_match else 'missing'})")
    if not license_match:
        raise RuntimeError(f"{family}: license missing in METADATA.pb")
    license_id = license_match.group(1).strip()
    if license_id not in ALLOWED_LICENSES:
        raise RuntimeError(f"{family}: unsupported license identifier {license_id!r}")
    blocks = re.findall(r"fonts\s*\{(.*?)\}", raw, re.DOTALL)
    candidates = []
    for block in blocks:
        style = re.search(r'style:\s*"([^"]+)"', block)
        filename = re.search(r'filename:\s*"([^"]+)"', block)
        weight = re.search(r'weight:\s*(\d+)', block)
        if style and filename and style.group(1).lower() == "normal":
            candidates.append((0 if weight and int(weight.group(1)) == 400 else 1, filename.group(1)))
    if not candidates:
        raise RuntimeError(f"{family}: no normal upright font file listed in metadata")
    candidates.sort()
    return slug, license_id, candidates[0][1]

def validate_font_file(path: Path, family: str) -> None:
    font = TTFont(str(path), lazy=False)
    try:
        names = []
        for record in font["name"].names:
            if record.nameID in (1, 16):
                try:
                    names.append(record.toUnicode())
                except Exception:
                    pass
        if slugify(family) not in {slugify(n) for n in names if n}:
            raise RuntimeError(f"{family}: font name table does not match family; names={sorted(set(names))[:8]}")
        cmap = set()
        for table in font["cmap"].tables:
            if table.isUnicode():
                cmap.update(table.cmap.keys())
        missing = sorted({ord(ch) for ch in SPECIMEN if not ch.isspace()} - cmap)
        if missing:
            raise RuntimeError(f"{family}: missing specimen glyph(s): {''.join(chr(c) for c in missing)!r}")
    finally:
        font.close()

def render_preview(font_path: Path, family: str, category: str, out_path: Path) -> None:
    width, height = 1400, 420
    image = Image.new("RGB", (width, height), "#F7F7F5")
    draw = ImageDraw.Draw(image)
    regular = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    draw.text((64, 46), family, font=regular, fill="#202124")
    draw.text((64, 94), category.replace("-", " ").upper(), font=small, fill="#73777D")
    draw.line((64, 142, width - 64, 142), fill="#D8DADD", width=2)
    size = 104
    while size >= 42:
        sample_font = ImageFont.truetype(str(font_path), size)
        box = draw.textbbox((0, 0), SPECIMEN, font=sample_font)
        if box[2] - box[0] <= width - 128:
            break
        size -= 4
    if size < 42:
        raise RuntimeError(f"{family}: specimen cannot fit preview canvas at readable size")
    draw.text((64, 190), SPECIMEN, font=sample_font, fill="#111315")
    draw.line((64, 340, width - 64, 340), fill="#E4E5E6", width=1)
    draw.text((64, 360), "Aa Bb Cc   0123456789", font=small, fill="#6B7076")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, format="PNG", optimize=True)

def build_one(item: tuple[str, str], work_dir: Path) -> dict[str, Any]:
    category, family = item
    slug, license_id, filename = fetch_metadata(family)
    metadata_url = f"https://github.com/google/fonts/blob/main/ofl/{slug}/METADATA.pb"
    encoded = urllib.parse.quote(filename, safe="(),.-_")
    font_url = f"{GOOGLE_FONTS}/ofl/{slug}/{encoded}"
    font_path = work_dir / "downloaded" / f"{slug}{Path(filename).suffix.lower()}"
    font_path.parent.mkdir(parents=True, exist_ok=True)
    font_path.write_bytes(fetch_bytes(font_url))
    if not 0 < font_path.stat().st_size <= 20 * 1024 * 1024:
        raise RuntimeError(f"{family}: invalid font file size {font_path.stat().st_size}")
    validate_font_file(font_path, family)
    preview_rel = f"previews/{slug}.png"
    preview_path = work_dir / "Font_Catalog_Pack" / preview_rel
    render_preview(font_path, family, category, preview_path)
    if preview_path.stat().st_size > 10 * 1024 * 1024:
        raise RuntimeError(f"{family}: preview exceeds 10 MB")
    return {"family": family, "display_name": family, "category": category, "source": "google",
            "license": license_id, "sort_order": CATALOG_INDEX[(category, family)],
            "preview": preview_rel, "_metadata_url": metadata_url}

def validate_manifest(records: list[dict[str, Any]], pack_dir: Path) -> None:
    required = {"family", "display_name", "category", "source", "license", "sort_order", "preview"}
    if len(records) != 72:
        raise RuntimeError(f"Expected 72 records, got {len(records)}")
    seen, orders, counts = set(), set(), Counter()
    for rec in records:
        if set(rec) != required:
            raise RuntimeError(f"{rec.get('family')}: manifest fields mismatch")
        key = (rec["source"], rec["family"])
        if key in seen or rec["sort_order"] in orders:
            raise RuntimeError(f"duplicate source+family or sort_order: {key}")
        seen.add(key); orders.add(rec["sort_order"])
        if rec["source"] != "google" or rec["license"] not in ALLOWED_LICENSES:
            raise RuntimeError(f"{rec['family']}: invalid source/license")
        rel = Path(rec["preview"])
        if not rec["preview"].startswith("previews/") or ".." in rel.parts:
            raise RuntimeError(f"{rec['family']}: unsafe preview path")
        preview = pack_dir / rel
        if not preview.is_file():
            raise RuntimeError(f"{rec['family']}: missing preview")
        with Image.open(preview) as img:
            img.verify()
        counts[rec["category"]] += 1
    expected = {name for name, _ in CATEGORIES}
    if set(counts) != expected or any(counts[c] != 6 for c in expected):
        raise RuntimeError(f"category counts invalid: {dict(counts)}")
    actual = {p.relative_to(pack_dir).as_posix() for p in pack_dir.rglob("*") if p.is_file()}
    expected_files = {"README.md", "fonts.json"} | {r["preview"] for r in records}
    if actual != expected_files:
        raise RuntimeError(f"extra/missing files: extra={actual-expected_files}, missing={expected_files-actual}")

def make_readme(records: list[dict[str, Any]]) -> str:
    lines = [
        "# Font Catalog Pack", "",
        "Bộ catalog gồm 72 font thuộc 12 category, mỗi category có 6 font.", "",
        "## Nguồn và license", "",
        "- Tất cả record dùng source=google; ứng dụng cần phân giải family qua tích hợp Google Fonts đã cấu hình.",
        "- License được đọc trực tiếp từ METADATA.pb trong repository chính thức Google Fonts tại thời điểm build.",
        "- fonts.json ghi identifier license đúng như metadata công bố. Không đóng gói binary vì source=google.",
        "- Preview được render bằng chính file TTF tải từ family tương ứng; file font chỉ dùng lúc build, không đưa vào ZIP.",
        "- License metadata là chứng cứ nguồn cho catalog; đội vận hành cần giữ lại metadata và đánh giá nghĩa vụ license/attribution trước khi publish.",
        "", "## Specimen", "", SPECIMEN, "",
        "## Danh sách family và chứng cứ metadata", "",
        "| Category | Family | License | Google Fonts metadata |", "|---|---|---|---|",
    ]
    for rec in records:
        lines.append(f"| {rec['category']} | {rec['family']} | {rec['license']} | [METADATA.pb]({rec['_metadata_url']}) |")
    lines += ["", "## Cấu trúc", "",
        "- fonts.json: JSON array theo đúng schema import, không có CMS fields nội bộ.",
        "- previews/: PNG thật được render từ đúng family binary.",
        "- Không có font-files/ vì tất cả record dùng source=google.",
        "", "## Kiểm tra", "",
        "Build chỉ thành công khi family metadata khớp chính xác, license hợp lệ, font parse được, name table khớp family và mọi ký tự trong specimen có glyph. Mỗi preview phải là PNG hợp lệ; mỗi category có đúng 6 record.",
        "", "Google Fonts integration phải được cấu hình trong ứng dụng để phân giải family. Catalog không chứa URL API giả hoặc media IDs.", ""]
    return "\n".join(lines)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dist")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    pack_dir = output / "Font_Catalog_Pack"
    pack_dir.mkdir()
    work_dir = output / "_work"
    work_dir.mkdir()
    items = [(cat, family) for cat, families in CATEGORIES for family in families]
    errors, records = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(build_one, item, work_dir): item for item in items}
        for future in as_completed(futures):
            item = futures[future]
            try:
                records.append(future.result())
                print(f"OK {item[0]} :: {item[1]}", flush=True)
            except Exception as exc:
                errors.append(f"{item[0]} :: {item[1]}: {exc}")
                print(f"FAIL {item[0]} :: {item[1]}: {exc}", file=sys.stderr, flush=True)
    if errors:
        raise RuntimeError("Font build failed:\n" + "\n".join(errors))
    records.sort(key=lambda rec: rec["sort_order"])
    public = [{k: v for k, v in rec.items() if not k.startswith("_")} for rec in records]
    (pack_dir / "fonts.json").write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (pack_dir / "README.md").write_text(make_readme(records), encoding="utf-8")
    validate_manifest(public, pack_dir)
    zip_path = output / "Font_Catalog_Pack.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(pack_dir.rglob("*")):
            if path.is_file():
                archive.write(path, Path("Font_Catalog_Pack") / path.relative_to(pack_dir))
    if zip_path.stat().st_size > 100 * 1024 * 1024:
        raise RuntimeError("ZIP exceeds 100 MB")
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip():
            raise RuntimeError("ZIP CRC validation failed")
        names = archive.namelist()
        if len(names) > 1200 or not names or any(not n.startswith("Font_Catalog_Pack/") for n in names):
            raise RuntimeError("ZIP root/count validation failed")
    shutil.rmtree(work_dir)
    print(f"SUCCESS: {len(public)} fonts, {len(public)} previews, {zip_path.stat().st_size} bytes", flush=True)
    print(f"ZIP_PATH={zip_path}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
