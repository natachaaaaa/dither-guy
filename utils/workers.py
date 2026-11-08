from __future__ import annotations

import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import Signal, QThread, QMutex

from .pipeline import render
from .constants import _VIDEO_WORKERS
from .gpu_kernels import GPU_BACKEND, to_gpu, gpu_palette_batch
from .palettes import PALETTES

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

_GPU_EXPORT_BATCH = 8


def _ffmpeg_mux_audio(video_only_path: str, source_video_path: str, output_path: str) -> bool:
    """Mux audio from source_video_path into video_only_path, write to output_path.
    Returns True on success, False if ffmpeg unavailable or source has no audio."""
    try:
        import imageio_ffmpeg
        ffmpeg_cmd = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_cmd = "ffmpeg"
        
    try:
        subprocess.run(
            [ffmpeg_cmd, "-version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

    cmd = [
        ffmpeg_cmd,
        "-y",
        "-i", video_only_path,
        "-i", source_video_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-shortest",
        output_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except Exception:
        return False


def finalize_video_output(tmp_path: str, final_path: str, muxed: bool) -> str | None:
    """After the audio mux attempt: keep the muxed file, or fall back to the
    silent temp render. Returns an error message, or None on success.
    (The temp file must only be deleted once the final file exists.)"""
    import shutil
    if not muxed:
        try:
            shutil.move(tmp_path, final_path)
        except Exception as exc:
            return f"Could not write {final_path}: {exc}"
    try:
        Path(tmp_path).unlink(missing_ok=True)
    except Exception:
        pass
    return None


class DitherWorker(QThread):
    """Renders one image with a params dict (see utils.pipeline.render)."""
    result_ready = Signal(object)
    error    = Signal(str)

    def __init__(self, img, params: dict, preview: bool = False):
        super().__init__()
        self._img = img
        self._p = dict(params)
        self._prev = preview
        self._stop = False; self._mutex = QMutex()

    def run(self):
        self.setPriority(QThread.Priority.LowPriority)
        try:
            t0     = time.perf_counter()
            result = render(self._img, self._p, preview=self._prev)
            elapsed = time.perf_counter() - t0
            self._mutex.lock()
            ok = not self._stop
            self._mutex.unlock()
            if ok:
                self.result_ready.emit((result, elapsed, self._prev))
            else:
                self.result_ready.emit(None)
        except MemoryError:
            self.error.emit("Out of memory — try smaller image or larger pixel size.")
        except Exception as exc:
            self.error.emit(f"Processing error: {exc}")

    def stop(self):
        self._mutex.lock(); self._stop = True; self._mutex.unlock()


class FrameDitherWorker(QThread):
    result_ready = Signal(object)
    
    def __init__(self, img: Image.Image, params: dict, preview: bool = True, is_video: bool = False,
                 t: float | None = None, frame: int = 0):
        super().__init__()
        self._img = img
        self._p = dict(params)
        self._preview = preview
        self._is_video = is_video
        self._t = t
        self._frame = frame
        self._stop = False
        self._mutex = QMutex()

    def run(self) -> None:
        self.setPriority(QThread.Priority.LowPriority)
        try:
            result = render(self._img, self._p, preview=self._preview, is_video=self._is_video,
                            t=self._t, frame=self._frame)
            self._mutex.lock()
            ok = not self._stop
            self._mutex.unlock()
            if ok:
                self.result_ready.emit(result)
            else:
                self.result_ready.emit(None)
        except Exception:
            import traceback
            traceback.print_exc()

    def stop(self) -> None:
        self._mutex.lock(); self._stop = True; self._mutex.unlock()


def _process_frame_worker(args):
    img, params, t, frame = args
    return render(img, params, is_video=True, t=t, frame=frame)


def _resolve_palette_rgb(palette_name: str, custom_palette) -> np.ndarray | None:
    if custom_palette is not None:
        arr = np.array(custom_palette, dtype=np.uint8)
        return arr if arr.ndim == 2 and arr.shape[1] == 3 else None
    pal = PALETTES.get(palette_name)
    if pal is None or palette_name == "B&W":
        return None
    try:
        arr = np.array(pal, dtype=np.uint8)
        return arr if arr.ndim == 2 and arr.shape[1] == 3 else None
    except Exception:
        return None


class _VideoExportBase(QThread):
    error = Signal(str)

    def __init__(self, video_path, save_path, params: dict, include_audio=True):
        super().__init__()
        self._vp = video_path; self._sp = save_path
        self._p = dict(params)
        self._include_audio = include_audio
        self._stop = False; self._mutex = QMutex()

    def _make_args(self, frames: list[Image.Image], start: int = 0, total: int = 0) -> list:
        """One job per frame; t = position in the clip (drives parameter animation)."""
        span = max(1, total - 1)
        return [(f, self._p, (start + i) / span if total else None, start + i)
                for i, f in enumerate(frames)]

    def _is_running(self) -> bool:
        self._mutex.lock()
        ok = not self._stop
        self._mutex.unlock()
        return ok

    def stop(self):
        self._mutex.lock(); self._stop = True; self._mutex.unlock()


class VideoExportWorker(_VideoExportBase):
    frame_ready = Signal(object)
    progress    = Signal(int, int)
    finished    = Signal()

    def run(self):
        if not _CV2:
            self.error.emit("opencv-python not installed."); return
        cap = out = None

        # If audio requested, write video to a temp file first, then mux.
        # Otherwise write directly to final path.
        if self._include_audio:
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
            import os; os.close(tmp_fd)
            write_path = tmp_path
        else:
            tmp_path   = None
            write_path = self._sp

        try:
            cap = cv2.VideoCapture(self._vp)
            if not cap.isOpened():
                self.error.emit("Failed to open video."); return

            fps   = cap.get(cv2.CAP_PROP_FPS) or 25.
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            BATCH = max(1, _VIDEO_WORKERS * 2)
            count = 0
            last_dithered = None
            frames_buf: list[Image.Image] = []

            with ThreadPoolExecutor(max_workers=_VIDEO_WORKERS) as executor:
                while self._is_running():
                    frames_buf.clear()
                    for _ in range(BATCH):
                        ret, frame = cap.read()
                        if not ret:
                            break
                        frames_buf.append(
                            Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
                    if not frames_buf:
                        break

                    dithered = list(executor.map(
                        _process_frame_worker, self._make_args(frames_buf, count, total)))

                    for dith in dithered:
                        if not self._is_running():
                            break
                        if out is None:
                            out = cv2.VideoWriter(
                                write_path,
                                cv2.VideoWriter_fourcc(*'mp4v'),
                                fps,
                                (dith.width, dith.height))
                        out.write(cv2.cvtColor(np.array(dith), cv2.COLOR_RGB2BGR))
                        count += 1
                        self.progress.emit(count, total)
                        last_dithered = dith

                    if last_dithered is not None and count % max(1, BATCH) == 0:
                        self.frame_ready.emit(last_dithered)

        except Exception as exc:
            self.error.emit(str(exc))
            return
        finally:
            if cap: cap.release()
            if out: out.release()

        # Mux audio from source into final output.
        if self._include_audio and tmp_path and self._is_running():
            muxed = _ffmpeg_mux_audio(tmp_path, self._vp, self._sp)
            err = finalize_video_output(tmp_path, self._sp, muxed)
            if err:
                self.error.emit(err)
                return
        elif tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

        self.finished.emit()


class GifExportWorker(_VideoExportBase):
    frame_ready = Signal(object)
    progress    = Signal(int, int)
    finished    = Signal()

    def run(self):
        if not _CV2:
            self.error.emit("opencv-python not installed."); return
        cap = None
        try:
            cap = cv2.VideoCapture(self._vp)
            if not cap.isOpened():
                self.error.emit("Failed to open video."); return

            fps         = cap.get(cv2.CAP_PROP_FPS) or 25.
            total       = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration_ms = max(20, int(1000 / fps))

            BATCH = max(1, _VIDEO_WORKERS * 2)

            frames: list[Image.Image] = []
            count = 0
            frames_buf: list[Image.Image] = []

            with ThreadPoolExecutor(max_workers=_VIDEO_WORKERS) as executor:
                while self._is_running():
                    frames_buf.clear()
                    for _ in range(BATCH):
                        ret, frame = cap.read()
                        if not ret:
                            break
                        frames_buf.append(
                            Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
                    if not frames_buf:
                        break

                    dithered = list(executor.map(
                        _process_frame_worker, self._make_args(frames_buf, count, total)))

                    for dith in dithered:
                        if not self._is_running():
                            break
                        frames.append(dith.convert("P", palette=Image.ADAPTIVE, colors=256))
                        count += 1
                        self.progress.emit(count, total)
                        if count % max(1, BATCH) == 0:
                            self.frame_ready.emit(dith)

            if frames and self._is_running():
                frames[0].save(
                    self._sp,
                    save_all=True,
                    append_images=frames[1:],
                    loop=0,
                    duration=duration_ms,
                    optimize=False,
                )
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if cap: cap.release()
