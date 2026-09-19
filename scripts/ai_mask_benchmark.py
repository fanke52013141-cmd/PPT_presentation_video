"""Offline AI Mask fixtures and scoring; never imports server or opens a database."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SIZE = (1920, 1080)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def font(size):
    for name in ("C:/Windows/Fonts/msyh.ttc", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise RuntimeError("Install Microsoft YaHei or DejaVuSans before generating fixtures")


def generate(root):
    if (root / "cases").exists():
        raise ValueError("cases already exists; choose a new output directory to preserve fixtures")
    specs = [
        ("01_separated", "独立卡片", 3, 48),
        ("02_gap_8px", "8px 白色间隔", 3, 8),
        ("03_gap_2px", "2px 白色间隔", 3, 2),
        ("04_arrow_bridge", "箭头粘连，箭头归左侧卡片", 3, 48),
        ("05_pale", "浅灰底板与细线", 3, 48),
        ("06_dense_15", "15 个独立讲解组", 15, 24),
        ("07_nested", "公共边框归标题，内部三组独立", 3, 48),
        ("08_detached", "文字、图标和装饰分离但同组", 3, 48),
    ]
    thumbs = []
    for case_id, title, count, gap in specs:
        folder = root / "cases" / case_id
        folder.mkdir(parents=True)
        image = Image.new("RGB", SIZE, "white")
        labels = np.zeros((SIZE[1], SIZE[0]), np.uint16)
        groups = []

        def add(gid, name, draw_fn):
            layer = Image.new("RGB", SIZE, "white")
            draw_fn(ImageDraw.Draw(layer))
            pixels = np.asarray(layer)
            mask = np.any(pixels != 255, axis=2)
            if np.any(mask & (labels != 0)):
                raise ValueError(f"Overlapping fixture ownership in {case_id}/{gid}")
            labels[mask] = gid
            image.paste(layer, (0, 0), Image.fromarray(mask.astype("uint8") * 255))
            Image.fromarray(mask.astype("uint8") * 255).save(folder / f"group_{gid:03d}.png")
            groups.append({"id": f"group_{gid:03d}", "narration": name})

        def header(d):
            d.text((90, 70), "数据如何变成决策", font=font(54), fill="#26334a")
            if case_id == "07_nested":
                d.rounded_rectangle((65, 220, 1855, 880), 30, outline="#8090a0", width=4)
        add(1, "标题与公共框架先出现", header)
        cols = 5 if count == 15 else 3
        rows = 3 if count == 15 else 1
        width = (1720 - (cols - 1) * gap) // cols
        height = 175 if rows == 3 else 430
        for i in range(count):
            x = 100 + (i % cols) * (width + gap)
            y = 270 + (i // cols) * 205
            name = f"步骤 {i + 1}：" + ("采集数据", "清洗数据", "分析结果")[i % 3]

            def card(d, x=x, y=y, i=i, name=name):
                pale = case_id == "05_pale"
                if case_id != "08_detached":
                    fill = "#FAFAFA" if pale else ("#e5f3ff", "#fff0df", "#e8f5e9")[i % 3]
                    d.rounded_rectangle((x, y, x + width - 1, y + height), 22,
                                        fill=fill, outline="#F7F7F7" if pale else "#668099", width=2)
                d.text((x + 20, y + 20), name, font=font(24 if rows == 3 else 32), fill="#253047")
                d.text((x + 20, y + 65), "输入 → 处理 → 输出", font=font(21 if rows == 3 else 28), fill="#435467")
                if rows == 1:
                    d.ellipse((x + 45, y + 140, x + 145, y + 240), outline="#5382a1", width=5)
                    d.rectangle((x + 175, y + 175, x + 255, y + 255), fill="#efbe73")
                    d.line((x + 40, y + 315, x + width - 40, y + 315), fill="#F8F8F8" if pale else "#768b99", width=2)
                    d.text((x + 20, y + 340), "完整区域同步出现", font=font(27), fill="#435467")
                    if case_id == "08_detached":
                        d.ellipse((x + width - 40, y + 260, x + width - 32, y + 268), fill="#d57c52")
                if case_id == "04_arrow_bridge" and i < count - 1:
                    right = x + width - 1
                    yy = y + 210
                    d.line((right, yy, right + gap, yy), fill="#354c65", width=3)
                    d.polygon(((right + gap, yy), (right + gap - 12, yy - 8), (right + gap - 12, yy + 8)), fill="#354c65")
            add(i + 2, name, card)
        image.save(folder / "image.png")
        Image.fromarray(labels).save(folder / "labels.png")
        write_json(folder / "groups.json", {"case_id": case_id, "description": title, "groups": groups,
                    "policy": "Visible nonwhite source pixels only; exact white is unscored background.",
                    "image_sha256": hashlib.sha256((folder / "image.png").read_bytes()).hexdigest()})
        thumb = image.resize((480, 270))
        ImageDraw.Draw(thumb).text((12, 235), case_id, fill="#111111", font=font(17))
        thumbs.append(thumb)
    sheet = Image.new("RGB", (960, 1080), "#dddddd")
    for i, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((i % 2) * 480, (i // 2) * 270))
    sheet.save(root / "contact_sheet.png")
    write_json(root / "dataset.json", {"version": 1, "size": SIZE, "cases": [s[0] for s in specs],
                 "font": "Microsoft YaHei preferred; keep delivered PNGs fixed across machines"})


def load_masks(case, prediction):
    groups = json.loads((case / "groups.json").read_text(encoding="utf-8"))["groups"]
    expected = {g["id"] for g in groups}
    unknown = {p.stem for p in prediction.glob("*.png")} - expected if prediction.exists() else set()
    if unknown:
        raise ValueError(f"Unknown masks in {prediction}: {sorted(unknown)}")
    masks = []
    for group in groups:
        path = prediction / (group["id"] + ".png")
        if path.exists():
            with Image.open(path) as im:
                if im.size != SIZE or im.mode != "L":
                    raise ValueError(f"Expected 1920x1080 grayscale binary mask: {path}")
                arr = np.asarray(im)
                if not np.isin(arr, [0, 255]).all():
                    raise ValueError(f"Mask must contain only 0 or 255: {path}")
                masks.append(arr != 0)
        else:
            masks.append(np.zeros((SIZE[1], SIZE[0]), bool))
    return groups, masks


def score_case(case, prediction):
    metadata = json.loads((case / "groups.json").read_text(encoding="utf-8"))
    if hashlib.sha256((case / "image.png").read_bytes()).hexdigest() != metadata["image_sha256"]:
        raise ValueError(f"Fixture image changed: {case}")
    gt = np.asarray(Image.open(case / "labels.png"))
    source = np.asarray(Image.open(case / "image.png").convert("RGB"))
    if gt.shape != (SIZE[1], SIZE[0]) or source.shape != (SIZE[1], SIZE[0], 3):
        raise ValueError("Fixture dimensions do not match the benchmark contract")
    if not np.array_equal(gt != 0, np.any(source != 255, axis=2)):
        raise ValueError("Ground-truth foreground does not match source pixels")
    foreground = gt != 0
    groups, masks = load_masks(case, prediction)
    counts = np.zeros(gt.shape, np.uint16)
    rows = []
    for index, (group, mask) in enumerate(zip(groups, masks), 1):
        truth = gt == index
        selected = mask & foreground
        tp = int(np.count_nonzero(selected & truth))
        fp = int(np.count_nonzero(selected & ~truth))
        fn = int(np.count_nonzero(truth & ~selected))
        rows.append({"id": group["id"], "iou": tp / max(1, tp + fp + fn),
                     "precision": tp / max(1, tp + fp), "recall": tp / max(1, tp + fn)})
        counts += mask.astype(np.uint16)
    missing = foreground & (counts == 0)
    pale = foreground & (source.min(axis=2) >= 245)
    coverage = 1 - np.count_nonzero(missing) / max(1, np.count_nonzero(foreground))
    overlap = int(np.count_nonzero(foreground & (counts > 1)))
    missed_difference = np.where(missing[..., None], 255 - source.astype(np.int16), 0)
    passed = coverage >= .995 and overlap == 0 and all(r["precision"] >= .99 and r["recall"] >= .99 for r in rows)
    return {"case_id": case.name, "passed": bool(passed), "macro_iou": float(np.mean([r["iou"] for r in rows])),
            "coverage": coverage, "overlap_foreground_pixels": overlap,
            "pale_recall": None if not pale.any() else float(np.count_nonzero(pale & (counts > 0)) / np.count_nonzero(pale)),
            "missing_source_rgb_mae": float(missed_difference.mean()), "groups": rows}


def score(root, prediction, report):
    cases = [root / "cases" / name for name in json.loads((root / "dataset.json").read_text())["cases"]]
    rows = [score_case(case, prediction / case.name) for case in cases]
    result = {"passed": all(r["passed"] for r in rows), "cases": rows,
              "note": "RGB MAE measures omitted source pixels only, NOT production renderer fidelity. White overlap is unscored."}
    write_json(report, result)
    print(json.dumps({"passed": result["passed"], "cases": [{k: r[k] for k in ("case_id", "passed", "macro_iou", "coverage", "pale_recall")} for r in rows]}, indent=2))
    return result


def baseline(root, output, radius, fine_grained=False, pale_threshold=254, enclosed_cap=20000):
    # Import only the side-effect-free detector. Ground truth is deliberately used
    # to choose the BEST owner per component: this is NOT an end-to-end AI score.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ai_mask_component_detection import detect_elements
    settings = dict(white_threshold=245, color_tolerance=12, closing_radius=radius,
                    add_border=2, connectivity=8, min_element_area=120, component_padding_px=12)
    if fine_grained:
        settings.update(fine_grained_detection=True, pale_support_threshold=pale_threshold,
                        enclosed_support_max_area_px=enclosed_cap)
    timings = []
    names = json.loads((root / "dataset.json").read_text())["cases"]
    for name in names:
        case = root / "cases" / name
        dest = output / name
        dest.mkdir(parents=True, exist_ok=True)
        gt = np.asarray(Image.open(case / "labels.png"))
        groups = json.loads((case / "groups.json").read_text(encoding="utf-8"))["groups"]
        masks = [np.zeros(gt.shape, np.uint8) for _ in groups]
        with tempfile.TemporaryDirectory(prefix="mask_bench_") as temp:
            started = time.perf_counter()
            payload = detect_elements(case / "image.png", Path(temp), settings)
            elapsed = time.perf_counter() - started
        elements = payload["elements"] + payload["residual_elements"]
        for element in elements:
            votes = np.zeros(len(groups) + 1, np.int64)
            runs = element["mask_rle"]["runs"]
            for y, x1, x2 in runs:
                votes += np.bincount(gt[y, x1:x2], minlength=len(votes))
            votes[0] = 0
            if votes.max() == 0:
                continue
            owner = int(votes.argmax()) - 1
            for y, x1, x2 in runs:
                masks[owner][y, x1:x2] = 255
        for group, mask in zip(groups, masks):
            Image.fromarray(mask).save(dest / (group["id"] + ".png"))
        timings.append({"case_id": name, "detector_cold_seconds": elapsed, "components": len(elements),
                        "detector_version": payload.get("version"),
                        "detection_settings_fingerprint": payload.get("detection_settings_fingerprint"),
                        "image_sha256": payload.get("source_sha256"),
                        "algorithm_version": payload.get("algorithm_version"),
                        "stage_timings_sec": payload.get("stage_timings_sec"),
                        "conflict_pixel_count": (payload.get("fine_grained") or {}).get("conflict_pixel_count"),
                        "unassigned_support_pixel_count": (payload.get("fine_grained") or {}).get("unassigned_support_pixel_count")})
        print(name, round(elapsed, 3), "seconds", flush=True)
    write_json(output / "timings.json", {"python": sys.version, "platform": platform.platform(), "settings": settings,
               "scope": "Detector only, cold cache, includes crop IO; no DocLayout, OCR, VLM, renderer, or memory measurement", "cases": timings})
    score(root, output, output / "report.json")


def selftest(root):
    with tempfile.TemporaryDirectory(prefix="mask_score_test_") as temp:
        base = Path(temp)
        case = root / "cases" / "01_separated"
        for p in case.glob("group_*.png"):
            (base / p.name).write_bytes(p.read_bytes())
        assert score_case(case, base)["passed"]
        a, b = base / "group_002.png", base / "group_003.png"
        first, second = a.read_bytes(), b.read_bytes()
        a.write_bytes(second); b.write_bytes(first)
        swapped = score_case(case, base)
        assert not swapped["passed"] and swapped["coverage"] == 1
        a.write_bytes(first); b.write_bytes(second)
        combined = np.maximum(np.asarray(Image.open(a)), np.asarray(Image.open(b)))
        Image.fromarray(combined).save(a)
        assert score_case(case, base)["overlap_foreground_pixels"] > 0
        a.write_bytes(first); b.unlink()
        assert score_case(case, base)["coverage"] < 1
    print("PASS: exact / swapped ownership / overlap / missing group")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["generate", "score", "baseline", "selftest"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--radius", type=int, choices=range(21), default=6)
    parser.add_argument("--fine-grained", action="store_true", help="run detection with fine_grained_detection enabled")
    parser.add_argument("--pale-threshold", type=int, choices=range(246, 256), default=254)
    parser.add_argument("--enclosed-cap", type=int, default=20000)
    args = parser.parse_args()
    if args.command == "generate":
        generate(args.root)
    elif args.command == "selftest":
        selftest(args.root)
    else:
        if args.output is None:
            parser.error("--output is required for baseline/score")
        if args.command == "baseline":
            if args.output.exists():
                parser.error("baseline output already exists; use a new directory")
            baseline(args.root, args.output, args.radius, fine_grained=args.fine_grained,
                     pale_threshold=args.pale_threshold, enclosed_cap=args.enclosed_cap)
        else:
            result = score(args.root, args.output, args.output / "report.json")
            sys.exit(0 if result["passed"] else 1)
