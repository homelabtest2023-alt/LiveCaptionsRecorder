from __future__ import annotations

import json
import os
import queue
import re
import sys
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, TextIO

import pythoncom
import uiautomation as auto


def configure_tk_runtime() -> None:
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            base_dir = Path(meipass)
    else:
        base_dir = Path(__file__).resolve().parent

    tcl_dir = base_dir / "tcl8.6"
    tk_dir = base_dir / "tk8.6"
    if tcl_dir.exists():
        os.environ["TCL_LIBRARY"] = str(tcl_dir)
    if tk_dir.exists():
        os.environ["TK_LIBRARY"] = str(tk_dir)


configure_tk_runtime()

from tkinter import filedialog, messagebox, scrolledtext, ttk


class AnimatedButton(tk.Button):
    def __init__(self, master, default_bg="#e6e6e6", hover_bg="#d9d9d9", default_fg="#000000", **kwargs):
        super().__init__(master, bg=default_bg, fg=default_fg, relief=tk.FLAT, bd=0, cursor="hand2", padx=10, pady=5, font=("Microsoft YaHei", 9), **kwargs)
        self.default_bg = default_bg
        self.hover_bg = hover_bg
        self.default_fg = default_fg
        
        self._current_color = self._hex_to_rgb(default_bg)
        self._target_color = self._current_color
        self._animating = False
        
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)

    def _hex_to_rgb(self, hex_color):
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join(c + c for c in hex_color)
        return [int(hex_color[i:i+2], 16) for i in (0, 2, 4)]

    def _rgb_to_hex(self, rgb):
        return f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"

    def on_enter(self, e):
        if self['state'] != tk.DISABLED:
            self._target_color = self._hex_to_rgb(self.hover_bg)
            if not self._animating:
                self._animate()

    def on_leave(self, e):
        if self['state'] != tk.DISABLED:
            self._target_color = self._hex_to_rgb(self.default_bg)
            if not self._animating:
                self._animate()

    def _animate(self):
        self._animating = True
        r, g, b = self._current_color
        tr, tg, tb = self._target_color
        
        dr = (tr - r) * 0.25
        dg = (tg - g) * 0.25
        db = (tb - b) * 0.25

        if abs(tr - r) < 2 and abs(tg - g) < 2 and abs(tb - b) < 2:
            self._current_color = self._target_color
            self.configure(bg=self._rgb_to_hex(self._current_color))
            self._animating = False
            return

        self._current_color = [r + dr, g + dg, b + db]
        try:
            self.configure(bg=self._rgb_to_hex(self._current_color))
            self.after(16, self._animate)
        except tk.TclError:
            pass

    def update_colors(self, default_bg, hover_bg, default_fg="#000000"):
        self.default_bg = default_bg
        self.hover_bg = hover_bg
        self.default_fg = default_fg
        self.configure(bg=default_bg, fg=default_fg)
        self._current_color = self._hex_to_rgb(default_bg)
        self._target_color = self._current_color


DEFAULT_KEYWORDS = "Live captions,字幕,caption"
POLL_INTERVAL_MS = 700
MIN_SEGMENT_DURATION_MS = 800
SEGMENT_IDLE_MS = 2200
MIN_TEXT_OVERLAP = 8
DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "LiveCaptionsRecorder" / "records"


def format_srt_timestamp(dt: datetime) -> str:
    """格式化 datetime 为 SRT 时间戳格式 (HH:MM:SS,mmm)"""
    return dt.strftime("%H:%M:%S,%f")[:-3]


@dataclass
class TranscriptSegment:
    start_at: datetime
    end_at: datetime
    text: str
    window_name: str

    @property
    def start_text(self) -> str:
        return self.start_at.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    @property
    def end_text(self) -> str:
        return self.end_at.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def to_dict(self) -> dict:
        return {
            "start": self.start_text,
            "end": self.end_text,
            "text": self.text,
            "window": self.window_name,
        }


def ensure_min_duration(start_at: datetime, end_at: datetime) -> datetime:
    minimum_end = start_at + timedelta(milliseconds=MIN_SEGMENT_DURATION_MS)
    return minimum_end if end_at < minimum_end else end_at


class SessionExporter:
    """流式写入导出器：每条字幕完成后立即落盘，防止长会议崩溃丢失数据。"""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._stamp = ""
        self._txt_handle: TextIO | None = None
        self._srt_handle: TextIO | None = None
        self._jsonl_handle: TextIO | None = None
        self._srt_index = 0

    def open(self, started_at: datetime) -> None:
        self._stamp = started_at.strftime("%Y%m%d_%H%M%S")
        self._txt_handle = (self.output_dir / f"captions_{self._stamp}.txt").open("w", encoding="utf-8")
        self._srt_handle = (self.output_dir / f"captions_{self._stamp}.srt").open("w", encoding="utf-8")
        self._jsonl_handle = (self.output_dir / f"captions_{self._stamp}.jsonl").open("w", encoding="utf-8")
        self._srt_index = 0

    def write(self, segment: TranscriptSegment) -> None:
        if self._txt_handle:
            self._txt_handle.write(f"[{segment.start_text} -> {segment.end_text}] {segment.text}\n")
            self._txt_handle.flush()
        if self._srt_handle:
            self._srt_index += 1
            self._srt_handle.write(f"{self._srt_index}\n")
            self._srt_handle.write(f"{format_srt_timestamp(segment.start_at)} --> {format_srt_timestamp(segment.end_at)}\n")
            self._srt_handle.write(f"{segment.text}\n\n")
            self._srt_handle.flush()
        if self._jsonl_handle:
            self._jsonl_handle.write(json.dumps(segment.to_dict(), ensure_ascii=False) + "\n")
            self._jsonl_handle.flush()

    def close(self) -> list[Path]:
        files: list[Path] = []
        for handle, ext in [
            (self._txt_handle, "txt"),
            (self._srt_handle, "srt"),
            (self._jsonl_handle, "jsonl"),
        ]:
            if handle:
                handle.close()
                path = self.output_dir / f"captions_{self._stamp}.{ext}"
                if self._srt_index > 0:
                    files.append(path)
                else:
                    path.unlink(missing_ok=True)
        self._txt_handle = self._srt_handle = self._jsonl_handle = None
        return files


class CaptionExtractor:
    _SPACES_RE = re.compile(r"\s+")
    _CACHE_REFRESH_POLLS = 300  # 每 ~3.5 分钟强制重新扫描一次，应对 Live Captions 重启

    def __init__(self) -> None:
        self._cached_control: auto.Control | None = None
        self._poll_count = 0

    @classmethod
    def normalize_text(cls, text: str) -> str:
        text = text.replace("\r", "\n")
        lines = [cls._SPACES_RE.sub(" ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    def iter_descendants(self, control: auto.Control) -> Iterable[auto.Control]:
        """优化遍历，避免不必要的深度。"""
        stack = [(control, 0)]
        while stack:
            current, depth = stack.pop()
            yield current
            if depth > 5:  # 字幕控件通常不会在太深的层级
                continue
            try:
                children = current.GetChildren()
            except Exception:  # noqa: BLE001
                continue
            for child in reversed(children):
                stack.append((child, depth + 1))

    def extract_text(self, window: auto.Control) -> str:
        # 定期清除缓存，防止超长会议中 Live Captions 重启后失效
        self._poll_count += 1
        if self._poll_count >= self._CACHE_REFRESH_POLLS:
            self._cached_control = None
            self._poll_count = 0

        # 1. 尝试使用缓存的控件
        if self._cached_control:
            try:
                # 快速验证控件是否仍然有效且属于当前窗口
                if self._cached_control.Exists(0, 0):
                    text = self.normalize_text(self._cached_control.Name or "")
                    if text and text.lower() not in {"settings", "close", "live captions"}:
                        return text
            except Exception:  # noqa: BLE001
                self._cached_control = None

        # 2. 缓存失效，重新搜索
        matches: list[tuple[int, str, auto.Control]] = []
        seen: set[str] = set()

        for control in self.iter_descendants(window):
            automation_id = (control.AutomationId or "").strip()
            class_name = (control.ClassName or "").strip()
            control_type = control.ControlTypeName or ""

            if automation_id in {"CaptionsTextBlock", "CaptionsScrollViewer"}:
                priority = 0
            elif control_type in {"TextControl", "DocumentControl", "EditControl"} and class_name in {
                "TextBlock",
                "ScrollViewer",
            }:
                priority = 1
            else:
                continue

            text = self.normalize_text(control.Name or "")
            if not text or len(text) <= 1:
                continue
            if text.lower() in {"settings", "close", "live captions"}:
                continue
            if text in seen:
                continue
            seen.add(text)
            matches.append((priority, text, control))

        if not matches:
            return ""

        # 排序并取优先级最高且长度最长的控件作为主字幕源
        matches.sort(key=lambda item: (item[0], -len(item[1])))
        self._cached_control = matches[0][2]
        # 始终只返回最优控件的文本，与缓存命中时行为一致，保证增量提取的正确性
        return matches[0][1]

    def dump_control_tree(self, window: auto.Control, max_depth: int = 10) -> str:
        lines: list[str] = []

        def walk(control: auto.Control, depth: int) -> None:
            if depth > max_depth:
                return
            indent = "  " * depth
            lines.append(
                f"{indent}{control.ControlTypeName} "
                f"name={self.normalize_text(control.Name or '')!r} "
                f"class={(control.ClassName or '').strip()!r} "
                f"aid={(control.AutomationId or '').strip()!r}"
            )
            try:
                children = control.GetChildren()
            except Exception as exc:  # noqa: BLE001
                lines.append(f"{indent}  ERROR {exc}")
                return
            for child in children:
                walk(child, depth + 1)

        walk(window, 0)
        return "\n".join(lines)


class TranscriptBuilder:
    MAX_DISPLAY_SEGMENTS = 20  # 内存中最多保留的已完成字幕条数（旧的已落盘）

    def __init__(self) -> None:
        self.snapshot_initialized = False
        self.previous_snapshot = ""
        self.active_segment: TranscriptSegment | None = None
        self.last_change_at: datetime | None = None
        self.completed_segments: list[TranscriptSegment] = []
        self._new_segments: list[TranscriptSegment] = []  # 待落盘的新完成字幕

    def drain_new_segments(self) -> list[TranscriptSegment]:
        """取出并清空待落盘队列，供调用方写入磁盘。"""
        result = self._new_segments
        self._new_segments = []
        return result

    def update(self, raw_text: str, captured_at: datetime, window_name: str) -> TranscriptSegment | None:
        raw_text = CaptionExtractor.normalize_text(raw_text)
        if not raw_text:
            return None

        if not self.snapshot_initialized:
            self.snapshot_initialized = True
            self.previous_snapshot = raw_text
            self.last_change_at = captured_at
            return None

        if raw_text == self.previous_snapshot:
            if self.active_segment is not None:
                self.active_segment.end_at = captured_at
            return None

        previous_change_at = self.last_change_at
        delta_text = self._extract_increment(raw_text)
        self.previous_snapshot = raw_text

        if not delta_text:
            self.last_change_at = captured_at
            return None

        if self.active_segment is None:
            self.active_segment = TranscriptSegment(captured_at, captured_at, delta_text, window_name)
            self.last_change_at = captured_at
            return self.active_segment

        if self._should_merge(previous_change_at, captured_at):
            self.active_segment.text = self._append_piece(self.active_segment.text, delta_text)
            self.active_segment.end_at = captured_at
            self.active_segment.window_name = window_name or self.active_segment.window_name
            self.last_change_at = captured_at
            return self.active_segment

        self._finalize_active(captured_at)
        self.active_segment = TranscriptSegment(captured_at, captured_at, delta_text, window_name)
        self.last_change_at = captured_at
        return self.active_segment

    def finish(self, finished_at: datetime) -> list[TranscriptSegment]:
        self._finalize_active(finished_at)
        return list(self.completed_segments)

    def _should_merge(self, previous_change_at: datetime | None, captured_at: datetime) -> bool:
        if previous_change_at is None:
            return False
        idle_ms = (captured_at - previous_change_at).total_seconds() * 1000
        return idle_ms <= SEGMENT_IDLE_MS

    def _extract_increment(self, current_snapshot: str) -> str:
        previous = self.previous_snapshot
        if not previous:
            return ""

        if previous in current_snapshot:
            return current_snapshot[len(previous) :].strip()

        overlap = self._suffix_prefix_overlap(previous, current_snapshot)
        if overlap >= MIN_TEXT_OVERLAP:
            return current_snapshot[overlap:].strip()
        return ""

    def _suffix_prefix_overlap(self, previous: str, current: str) -> int:
        max_size = min(len(previous), len(current))
        for size in range(max_size, MIN_TEXT_OVERLAP - 1, -1):
            if previous[-size:] == current[:size]:
                return size
        return 0

    def _append_piece(self, current_text: str, delta_text: str) -> str:
        if not current_text:
            return delta_text
        if delta_text in current_text:
            return current_text
        overlap = self._suffix_prefix_overlap(current_text, delta_text)
        if overlap >= MIN_TEXT_OVERLAP:
            return current_text + delta_text[overlap:]
        if current_text.endswith(delta_text):
            return current_text
        separator = "\n" if ("\n" in current_text or "\n" in delta_text) else ""
        return current_text + separator + delta_text

    def _finalize_active(self, end_at: datetime) -> None:
        if self.active_segment is None:
            return

        self.active_segment.end_at = ensure_min_duration(self.active_segment.start_at, end_at)
        text = self.active_segment.text.strip()
        if text:
            if self.completed_segments and self.completed_segments[-1].text == text:
                self.completed_segments[-1].end_at = self.active_segment.end_at
            else:
                self.completed_segments.append(self.active_segment)
                self._new_segments.append(self.active_segment)
                # 超出显示缓冲区的旧条目已落盘，可从内存中移除
                if len(self.completed_segments) > self.MAX_DISPLAY_SEGMENTS:
                    del self.completed_segments[:-self.MAX_DISPLAY_SEGMENTS]

        self.active_segment = None
        self.last_change_at = None


class LiveCaptionsFinder:
    def __init__(self, keywords: Iterable[str]) -> None:
        self.update_keywords(keywords)

    def update_keywords(self, keywords: Iterable[str]) -> None:
        self.keywords = [value.strip().lower() for value in keywords if value.strip()]

    def list_top_windows(self) -> list[str]:
        results: list[str] = []
        for window in auto.GetRootControl().GetChildren():
            name = (window.Name or "").strip() or "<无标题>"
            class_name = (window.ClassName or "").strip() or "<无类名>"
            automation_id = (window.AutomationId or "").strip()
            suffix = f" | {automation_id}" if automation_id else ""
            results.append(f"{name} | {class_name}{suffix}")
        return results

    def find_window(self) -> auto.Control | None:
        for window in auto.GetRootControl().GetChildren():
            if self._matches((window.Name or "").strip(), (window.ClassName or "").strip()):
                return window
        return None

    def _matches(self, name: str, class_name: str) -> bool:
        haystacks = (name.lower(), class_name.lower())
        for keyword in self.keywords:
            if any(keyword in hay for hay in haystacks):
                return True
        return False


class RecorderWorker:
    def __init__(self, finder: LiveCaptionsFinder, message_queue: queue.Queue[tuple[str, object]]) -> None:
        self.finder = finder
        self.message_queue = message_queue
        self.extractor = CaptionExtractor()
        self.exporter: SessionExporter | None = None
        self.builder = TranscriptBuilder()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._output_dir: Path | None = None
        self._segment_count = 0
        self._total_segment_count = 0  # 跨内存裁剪的累计已保存条数
        self.session_started_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, output_dir: Path) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self.builder = TranscriptBuilder()
        self.exporter = SessionExporter(output_dir)
        self._output_dir = output_dir
        self._segment_count = 0
        self._total_segment_count = 0
        self.session_started_at = datetime.now()
        self.exporter.open(self.session_started_at)  # 立即建立文件，之后增量写入
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.message_queue.put(("status", f"开始新会话：{self.session_started_at.strftime('%Y-%m-%d %H:%M:%S')}"))
        self.message_queue.put(("status", "已建立基线，开始后不会记录开始前已经存在的旧字幕"))
        self.message_queue.put(("status", f"实时保存到：{output_dir}"))

    def stop(self) -> None:
        if not self.running:
            return

        self._stop_event.set()
        self.message_queue.put(("status", "正在停止并保存记录..."))

    def _run(self) -> None:
        missing_window_reported = False
        last_error = ""
        with auto.UIAutomationInitializerInThread():
            while not self._stop_event.is_set():
                try:
                    window = self.finder.find_window()
                    if window is None:
                        if not missing_window_reported:
                            self.message_queue.put(("status", "未找到字幕窗口，正在重试"))
                            missing_window_reported = True
                        time.sleep(POLL_INTERVAL_MS / 1000)
                        continue

                    missing_window_reported = False
                    raw_text = self.extractor.extract_text(window)
                    if not raw_text:
                        time.sleep(POLL_INTERVAL_MS / 1000)
                        continue

                    active = self.builder.update(
                        raw_text=raw_text,
                        captured_at=datetime.now(),
                        window_name=(window.Name or "").strip(),
                    )

                    # 每条字幕完成后立即落盘，不等待会话结束
                    for seg in self.builder.drain_new_segments():
                        if self.exporter:
                            self.exporter.write(seg)
                        self._total_segment_count += 1

                    if active is not None:
                        display_lines = []
                        # 显示最近的 2 条已完成字幕
                        for seg in self.builder.completed_segments[-2:]:
                            time_str = seg.start_at.strftime('%H:%M:%S')
                            display_lines.append(f"[{time_str}] {seg.text}")
                        
                        # 显示当前正在识别的实时字幕
                        active_time = active.start_at.strftime('%H:%M:%S')
                        lines = active.text.split("\n")
                        active_text_display = "\n".join(lines[-3:]) if len(lines) > 3 else active.text
                        display_lines.append(f"[{active_time} 实时...] {active_text_display}")

                        self.message_queue.put(("caption", "\n".join(display_lines)))

                        if self._total_segment_count != self._segment_count:
                            self._segment_count = self._total_segment_count
                            self.message_queue.put(("status", f"已整理 {self._segment_count} 条字幕"))
                        last_error = ""
                except Exception as exc:  # noqa: BLE001
                    message = f"抓取异常：{exc}"
                    if message != last_error:
                        self.message_queue.put(("status", message))
                        last_error = message

                time.sleep(POLL_INTERVAL_MS / 1000)

        # 收尾：将最后一段活跃字幕落盘
        finished_at = datetime.now()
        self.builder.finish(finished_at)
        for seg in self.builder.drain_new_segments():
            if self.exporter:
                self.exporter.write(seg)
            self._total_segment_count += 1

        files: list[Path] = []
        if self.exporter is not None:
            files = self.exporter.close()

        if files:
            saved_names = " / ".join(path.name for path in files)
            self.message_queue.put(("status", f"已保存 {self._total_segment_count} 条字幕：{saved_names}"))
        else:
            self.message_queue.put(("status", "本次没有可保存的字幕内容"))
            
        self.session_started_at = None
        self.message_queue.put(("stopped", None))


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Live Captions Recorder")
        self.root.geometry("940x700")

        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.output_dir_var = tk.StringVar(value=str(DEFAULT_OUTPUT_DIR))
        self.keywords_var = tk.StringVar(value=DEFAULT_KEYWORDS)
        self.status_var = tk.StringVar(value="就绪")
        self.preview_var = tk.StringVar(value="暂无字幕")

        self._load_config()

        self.finder = LiveCaptionsFinder(self._current_keywords())
        self.extractor = CaptionExtractor()
        self.recorder = RecorderWorker(self.finder, self.messages)

        self.toggle_button: tk.Button | None = None
        self._close_deadline: float = 0.0

        self._build_ui()
        self._set_recording_state(False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(200, self._drain_messages)

    def _get_config_path(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "config.json"
        return Path(__file__).resolve().parent / "config.json"

    def _load_config(self) -> None:
        path = self._get_config_path()
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.output_dir_var.set(config.get("output_dir", str(DEFAULT_OUTPUT_DIR)))
                    self.keywords_var.set(config.get("keywords", DEFAULT_KEYWORDS))
            except Exception:  # noqa: BLE001
                pass

    def _save_config(self) -> None:
        path = self._get_config_path()
        config = {
            "output_dir": self.output_dir_var.get(),
            "keywords": self.keywords_var.get(),
        }
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.configure("TLabel", font=("Microsoft YaHei", 9))
        style.configure("TEntry", font=("Microsoft YaHei", 9))
        
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="输出目录").grid(row=0, column=0, sticky="w", pady=(0, 10))
        ttk.Entry(frame, textvariable=self.output_dir_var, width=78).grid(row=0, column=1, sticky="ew", padx=(10, 10), pady=(0, 10))
        AnimatedButton(frame, text="选择...", command=self.select_output_dir).grid(row=0, column=2, sticky="e", pady=(0, 10))

        ttk.Label(frame, text="窗口关键字").grid(row=1, column=0, sticky="w", pady=(0, 10))
        ttk.Entry(frame, textvariable=self.keywords_var, width=78).grid(row=1, column=1, sticky="ew", padx=(10, 10), pady=(0, 10))
        AnimatedButton(frame, text="应用关键字", command=self.apply_keywords).grid(row=1, column=2, sticky="e", pady=(0, 10))

        button_row = ttk.Frame(frame)
        button_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 10))

        self.toggle_button = AnimatedButton(
            button_row,
            text="开始记录",
            command=self.toggle_recording,
            default_bg="#e6e6e6",
            hover_bg="#d9d9d9",
            width=12,
        )
        self.toggle_button.pack(side=tk.LEFT)

        AnimatedButton(button_row, text="打开系统字幕", command=self.open_live_captions, default_bg="#e1f5fe", hover_bg="#b3e5fc").pack(side=tk.LEFT, padx=(10, 0))
        AnimatedButton(button_row, text="导出控件树", command=self.export_control_tree).pack(side=tk.LEFT, padx=(10, 0))
        AnimatedButton(button_row, text="打开输出目录", command=self.open_output_dir).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(frame, text="状态").grid(row=3, column=0, sticky="nw", pady=(10, 0))
        ttk.Label(frame, textvariable=self.status_var, wraplength=700).grid(
            row=3,
            column=1,
            columnspan=2,
            sticky="w",
            pady=(10, 0),
        )

        ttk.Label(frame, text="当前字幕").grid(row=4, column=0, sticky="nw", pady=(10, 0))
        preview = tk.Label(
            frame,
            textvariable=self.preview_var,
            relief=tk.FLAT,
            bg="#f9f9f9",
            anchor="nw",
            justify=tk.LEFT,
            padx=10,
            pady=10,
            wraplength=700,
            font=("Microsoft YaHei", 10)
        )
        preview.grid(row=4, column=1, columnspan=2, sticky="nsew", pady=(10, 0))

        ttk.Label(frame, text="运行日志").grid(row=5, column=0, sticky="nw", pady=(10, 0))
        self.log_text = scrolledtext.ScrolledText(frame, height=20, width=98, state=tk.DISABLED, font=("Consolas", 9), bg="#f4f4f4", relief=tk.FLAT)
        self.log_text.grid(row=5, column=1, columnspan=2, sticky="nsew", pady=(10, 0))

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

    def _set_recording_state(self, recording: bool) -> None:
        if self.toggle_button is not None:
            if recording:
                self.toggle_button.configure(text="停止记录")
                self.toggle_button.update_colors("#d9534f", "#c9302c", "#ffffff")
            else:
                self.toggle_button.configure(text="开始记录")
                self.toggle_button.update_colors("#e6e6e6", "#d9d9d9", "#000000")

    def open_live_captions(self) -> None:
        try:
            subprocess.Popen(["cmd", "/c", "start", "", "livecaptions.exe"])
            self.status_var.set("正在尝试打开 Windows 内建字幕...")
            self._append_log("正在尝试打开 Windows 内建字幕")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("启动失败", f"无法打开系统字幕：{exc}")

    def _current_keywords(self) -> list[str]:
        return [part.strip() for part in self.keywords_var.get().split(",") if part.strip()]

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')} {text}\n")
        # 超长会议日志裁剪：超过 1200 行时删除最旧的 200 行，保留约 1000 行
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 1200:
            self.log_text.delete("1.0", "201.0")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def apply_keywords(self) -> None:
        keywords = self._current_keywords()
        self.finder.update_keywords(keywords)
        self.status_var.set("关键字已更新")
        self._append_log(f"已更新关键字：{', '.join(keywords)}")
        self._save_config()

    def select_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if selected:
            self.output_dir_var.set(selected)
            self._save_config()

    def open_output_dir(self) -> None:
        output_dir = Path(self.output_dir_var.get()).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(output_dir)

    def toggle_recording(self) -> None:
        if self.recorder.running:
            self.recorder.stop()
            if self.toggle_button:
                self.toggle_button.configure(text="正在停止...", state=tk.DISABLED)
        else:
            self.apply_keywords()
            try:
                self._clear_log()
                self.recorder.start(Path(self.output_dir_var.get()).expanduser())
                self.preview_var.set("等待字幕中...")
                self._set_recording_state(True)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("启动失败", str(exc))

    def export_control_tree(self) -> None:
        self.apply_keywords()
        window = self.finder.find_window()
        if window is None:
            messagebox.showwarning("未找到窗口", "当前关键字没有匹配到字幕窗口。")
            return

        output_dir = Path(self.output_dir_var.get()).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = output_dir / f"control_tree_{stamp}.txt"
        path.write_text(self.extractor.dump_control_tree(window), encoding="utf-8")
        self.status_var.set(f"已导出控件树：{path.name}")
        self._append_log(f"已导出控件树：{path}")

    def _drain_messages(self) -> None:
        while True:
            try:
                kind, payload = self.messages.get_nowait()
            except queue.Empty:
                break

            if kind == "status":
                self.status_var.set(str(payload))
                self._append_log(str(payload))
            elif kind == "caption":
                self.preview_var.set(str(payload))
            elif kind == "stopped":
                self._set_recording_state(False)
                if self.toggle_button:
                    self.toggle_button.configure(state=tk.NORMAL)
        self.root.after(200, self._drain_messages)

    def on_close(self) -> None:
        if self.recorder.running:
            self.recorder.stop()
            self._close_deadline = time.monotonic() + 15  # 最多等待 15 秒存盘
            self.root.after(200, self._wait_and_close)
        else:
            self._save_config()
            self.root.destroy()

    def _wait_and_close(self) -> None:
        if self.recorder.running and time.monotonic() < self._close_deadline:
            self.root.after(200, self._wait_and_close)
        else:
            self._save_config()
            self.root.destroy()


def main() -> None:
    auto.SetGlobalSearchTimeout(3)
    root = tk.Tk()
    style = ttk.Style()
    if "vista" in style.theme_names():
        style.theme_use("vista")
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
