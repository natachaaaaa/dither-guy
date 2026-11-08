import sys
import argparse
import faulthandler
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt

from ui.window import DitherGuy
from utils.constants import VERSION

def selftest(report_path: str) -> int:
    """Exercise the bundled app without showing a window.

    Builds the real main window offscreen, loads every preset into the control
    panel and renders it, plus layers / FX / ASCII / custom matrix / exports.
    Writes a report and returns a process exit code.
    """
    import os
    import tempfile
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines, failures = [], 0
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        from utils.theme import load_fonts
        load_fonts()
        from utils.pipeline import render
        from utils.presets import list_presets, load_preset, PRESETS_DIR
        from utils.ui_preset_browser import sample_image
        from utils.export import export_image, EXPORT_FORMATS
        from utils.gpu_kernels import GPU_BACKEND
        from utils.dither_kernels import _NUMBA

        w = DitherGuy()
        panel = w.image_controls
        src = sample_image(160, 112)
        names = list_presets()
        lines.append(f"version {VERSION} | backend {GPU_BACKEND} | numba {_NUMBA} | presets dir {PRESETS_DIR}")
        if len(names) < 50:
            failures += 1
            lines.append(f"FAIL only {len(names)} presets found")
        for name in names:
            try:
                panel.set_params(load_preset(name))
                render(src, panel.get_params())
                lines.append(f"ok   preset {name}")
            except Exception as exc:
                failures += 1
                lines.append(f"FAIL preset {name}: {exc!r}")
        extra = dict(method="Custom Matrix", custom_matrix=[[0, 1], [1, 0]], pixel_size=2,
                     palette_name="Synthwave", color=(255, 255, 255),
                     layer=dict(enabled=True, mask_mode="Left → Right", mask_pos=50, feather=10,
                                params=load_preset(names[0]) if names else {}),
                     fx=dict(scanlines=50, chroma=50, curvature=30, noise=10, vignette=30,
                             rgb_split=20, block_glitch=20, pixel_sort=20, seed=1),
                     glow_radius=6, glow_intensity=50, glow_gradient=[(255, 0, 128), (0, 220, 255)],
                     glow_mode="Radial")
        for label, p in (("features", extra),
                         ("ascii", dict(extra, ascii=dict(enabled=True, cell=6)))):
            try:
                img = render(src, p)
                lines.append(f"ok   {label} {img.size}")
            except Exception as exc:
                failures += 1
                lines.append(f"FAIL {label}: {exc!r}")
        out_dir = tempfile.mkdtemp(prefix="ditherguy_selftest_")
        img = render(src, dict(extra, fx=None, layer=None, glow_radius=0))
        for fmt, (ext, _) in EXPORT_FORMATS.items():
            try:
                export_image(img, os.path.join(out_dir, "x" + ext), fmt, 2, extra, src)
                lines.append(f"ok   export {fmt}")
            except Exception as exc:
                failures += 1
                lines.append(f"FAIL export {fmt}: {exc!r}")
        w.close()
    except Exception:
        failures += 1
        lines.append("FAIL startup:\n" + traceback.format_exc())
    lines.append("RESULT " + ("OK" if failures == 0 else f"{failures} FAILURE(S)"))
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass
    print("\n".join(lines))
    return 0 if failures == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Dither Guy")
    parser.add_argument("--debug", action="store_true", help="Enable developer debug mode")
    parser.add_argument("--selftest", metavar="REPORT", nargs="?", const="selftest.txt",
                        help="Render every preset headlessly, write a report file and exit (0 = OK). Used by CI on the built executable.")
    args = parser.parse_args()

    if args.selftest:
        sys.exit(selftest(args.selftest))

    if args.debug:
        faulthandler.enable()
        print("Debug mode enabled. Faulthandler active.", file=sys.stderr)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Dither Guy")
    app.setApplicationVersion(VERSION)

    from utils.theme import load_fonts
    load_fonts()

    if args.debug:
        def debug_excepthook(exc_type, exc_value, exc_tb):
            tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            print("UNHANDLED EXCEPTION:\n" + tb_str, file=sys.stderr)
            try:
                QMessageBox.critical(None, "Fatal Debug Error", f"App crashed:\n\n{exc_value}\n\nCheck terminal for full stacktrace.")
            except Exception:
                pass
            sys.exit(1)
        sys.excepthook = debug_excepthook

    w = DitherGuy()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    try:
        multiprocessing.set_start_method('spawn')
    except RuntimeError:
        pass
    main()
