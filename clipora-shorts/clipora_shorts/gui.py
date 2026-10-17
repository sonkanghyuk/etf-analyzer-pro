"""Clipora Shorts 창 화면 (tkinter, 파이썬 기본 포함).

실행: python -m clipora_shorts.gui [영상파일]
"""

import contextlib
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import cli, config, templates

WHISPER = {"빠름 (base)": "base", "보통 (small) · 추천": "small", "정확 (medium) · 느림": "medium"}
VIDEO_TYPES = [("영상 파일", "*.mp4 *.mov *.mkv *.avi *.m4v *.webm *.MP4 *.MOV"), ("모든 파일", "*.*")]


class QueueWriter:
    """작업 스레드의 출력(print)을 화면으로 넘깁니다."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s: str) -> int:
        if s:
            self.q.put(("text", s))
        return len(s)

    def flush(self) -> None:
        pass


def open_folder(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App:
    def __init__(self, root: tk.Tk, initial: str | None = None, on_done=None, echo: bool = False):
        self.root, self.on_done, self.echo = root, on_done, echo
        self.q: queue.Queue = queue.Queue()
        self.running = False
        self.out_dir: Path | None = None
        cfg = config.load()

        root.title("Clipora Shorts — 촬영본을 숏폼으로")
        root.geometry("760x680")
        root.minsize(640, 560)
        f = ttk.Frame(root, padding=16)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="촬영본을 고르면 AI가 하이라이트를 골라 자막 입힌 9:16 숏폼을 만들어요.",
                  font=("", 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        self.video = tk.StringVar(value=initial or "")
        ttk.Label(f, text="영상 파일").grid(row=1, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.video).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="찾아보기…", command=self.browse).grid(row=1, column=2)

        opts = ttk.LabelFrame(f, text="옵션", padding=10)
        opts.grid(row=2, column=0, columnspan=3, sticky="ew", pady=10)
        for c in (1, 3):
            opts.columnconfigure(c, weight=1)

        names = [f"{t.name} ({t.id})" for t in templates.TEMPLATES.values()]
        self.template = tk.StringVar(value=cfg.get("template_label", names[1]))
        ttk.Label(opts, text="템플릿").grid(row=0, column=0, sticky="w")
        ttk.Combobox(opts, textvariable=self.template, values=names, state="readonly").grid(row=0, column=1, sticky="ew", padx=6)

        self.count = tk.StringVar(value="자동")
        ttk.Label(opts, text="개수").grid(row=0, column=2, sticky="w")
        ttk.Combobox(opts, textvariable=self.count, values=["자동"] + [str(i) for i in range(1, 11)],
                     state="readonly", width=8).grid(row=0, column=3, sticky="w", padx=6)

        self.min_len, self.max_len = tk.StringVar(value="20"), tk.StringVar(value="60")
        ttk.Label(opts, text="길이(초)").grid(row=1, column=0, sticky="w", pady=6)
        lens = ttk.Frame(opts)
        lens.grid(row=1, column=1, sticky="w", padx=6)
        ttk.Spinbox(lens, from_=5, to=170, textvariable=self.min_len, width=5).pack(side="left")
        ttk.Label(lens, text=" ~ ").pack(side="left")
        ttk.Spinbox(lens, from_=10, to=180, textvariable=self.max_len, width=5).pack(side="left")

        self.start, self.end = tk.StringVar(), tk.StringVar()
        ttk.Label(opts, text="구간").grid(row=1, column=2, sticky="w")
        rng = ttk.Frame(opts)
        rng.grid(row=1, column=3, sticky="w", padx=6)
        ttk.Entry(rng, textvariable=self.start, width=8).pack(side="left")
        ttk.Label(rng, text=" ~ ").pack(side="left")
        ttk.Entry(rng, textvariable=self.end, width=8).pack(side="left")
        ttk.Label(rng, text=" (예: 10:00, 비우면 전체)", foreground="gray").pack(side="left")

        self.whisper = tk.StringVar(value=cfg.get("whisper_label", "보통 (small) · 추천"))
        ttk.Label(opts, text="음성인식").grid(row=2, column=0, sticky="w")
        ttk.Combobox(opts, textvariable=self.whisper, values=list(WHISPER), state="readonly").grid(row=2, column=1, sticky="ew", padx=6)

        self.persona = tk.StringVar(value=cfg.get("persona", ""))
        ttk.Label(opts, text="채널 성격").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Entry(opts, textvariable=self.persona).grid(row=3, column=1, columnspan=3, sticky="ew", padx=6)

        self.api_key = tk.StringVar(value=cfg.get("anthropic_api_key", ""))
        ttk.Label(opts, text="Claude API 키").grid(row=4, column=0, sticky="w")
        ttk.Entry(opts, textvariable=self.api_key, show="•").grid(row=4, column=1, columnspan=2, sticky="ew", padx=6)
        link = ttk.Label(opts, text="키 발급받기 ↗", foreground="#4c6ef5", cursor="hand2")
        link.grid(row=4, column=3, sticky="w")
        link.bind("<Button-1>", lambda e: webbrowser.open("https://console.anthropic.com/settings/keys"))
        ttk.Label(opts, text="키가 없으면 규칙 기반으로 고릅니다. 키는 이 PC에만 저장돼요.", foreground="gray").grid(
            row=5, column=1, columnspan=3, sticky="w", padx=6)

        btns = ttk.Frame(f)
        btns.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.run_btn = ttk.Button(btns, text="✨ 숏폼 만들기", command=self.run)
        self.run_btn.pack(side="left")
        self.demo_btn = ttk.Button(btns, text="샘플로 시험해 보기", command=lambda: self.run(demo=True))
        self.demo_btn.pack(side="left", padx=6)
        self.open_btn = ttk.Button(btns, text="📂 결과 폴더 열기", command=lambda: open_folder(self.out_dir), state="disabled")
        self.open_btn.pack(side="right")
        self.copy_btn = ttk.Button(btns, text="📋 기록 복사", command=self.copy_log)
        self.copy_btn.pack(side="right", padx=6)

        self.bar = ttk.Progressbar(f, mode="indeterminate")
        self.bar.grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        self.log = tk.Text(f, height=14, wrap="word", state="disabled", font=("Consolas", 10) if sys.platform.startswith("win") else None)
        self.log.grid(row=5, column=0, columnspan=3, sticky="nsew")
        f.rowconfigure(5, weight=1)
        root.after(100, self.poll)

    # ---------- 입력 ----------
    def browse(self):
        path = filedialog.askopenfilename(title="촬영본 선택", filetypes=VIDEO_TYPES)
        if path:
            self.video.set(path)

    def build_args(self, demo: bool) -> list[str] | None:
        tpl_id = self.template.get().rsplit("(", 1)[-1].rstrip(")")
        if demo:
            self.out_dir = Path.home() / "Clipora_샘플"
            return ["--demo", "-o", str(self.out_dir / "결과"), "-t", tpl_id]
        video = Path(self.video.get().strip().strip('"'))
        if not video.is_file():
            messagebox.showwarning("Clipora Shorts", "영상 파일을 먼저 골라 주세요.")
            return None
        try:
            lo, hi = float(self.min_len.get()), float(self.max_len.get())
        except ValueError:
            messagebox.showwarning("Clipora Shorts", "길이는 숫자로 적어 주세요.")
            return None
        self.out_dir = video.with_name(f"{video.stem}_shorts")
        args = [str(video), "-o", str(self.out_dir), "-t", tpl_id, "--min", str(lo), "--max", str(hi),
                "--whisper", WHISPER.get(self.whisper.get(), "small")]
        if self.count.get() != "자동":
            args += ["-n", self.count.get()]
        if self.start.get().strip():
            args += ["--start", self.start.get().strip()]
        if self.end.get().strip():
            args += ["--end", self.end.get().strip()]
        if self.persona.get().strip():
            args += ["--persona", self.persona.get().strip()]
        return args

    # ---------- 실행 ----------
    def run(self, demo: bool = False):
        if self.running:
            return
        args = self.build_args(demo)
        if args is None:
            return
        key = self.api_key.get().strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
        config.save({**config.load(), "anthropic_api_key": key, "template_label": self.template.get(),
                     "whisper_label": self.whisper.get(), "persona": self.persona.get()})
        self.running = True
        for b in (self.run_btn, self.demo_btn):
            b.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.clear_log()
        self.bar.start(12)
        threading.Thread(target=self.work, args=(args,), daemon=True).start()

    def work(self, args: list[str]):
        writer = QueueWriter(self.q)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                code = cli.main(args)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            if e.code and not isinstance(e.code, int):
                self.q.put(("text", f"{e.code}\n"))
        except Exception as e:  # 예상 못 한 오류도 화면에 보여 줍니다
            self.q.put(("text", f"\n❌ 오류: {type(e).__name__}: {e}\n"))
            code = 1
        self.q.put(("done", code))

    def poll(self):
        try:
            while True:
                kind, value = self.q.get_nowait()
                if kind == "text":
                    self.append(value)
                else:
                    self.finish(value)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def append(self, s: str):
        if self.echo:  # 자체 시험 때는 콘솔에도 그대로 남깁니다
            sys.__stdout__.buffer.write(s.encode("utf-8", "replace"))
            sys.__stdout__.flush()
        self.log.configure(state="normal")
        for i, part in enumerate(s.split("\r")):
            if i > 0:  # 진행 막대(\r): 현재 줄을 덮어씁니다
                self.log.delete("end-1c linestart", "end-1c")
            self.log.insert("end", part)
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def log_text(self) -> str:
        return self.log.get("1.0", "end").strip()

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_text())
        messagebox.showinfo("Clipora Shorts", "기록을 복사했어요. 채팅창에 붙여넣어 보내 주세요.")

    def save_log(self) -> Path | None:
        """실패했을 때 기록을 파일로 남깁니다 (사용자 설정 폴더/마지막_기록.txt)."""
        try:
            path = config.path().parent / "마지막_기록.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.log_text(), encoding="utf-8")
            return path
        except OSError:
            return None

    def finish(self, code: int):
        self.running = False
        self.bar.stop()
        for b in (self.run_btn, self.demo_btn):
            b.configure(state="normal")
        ok = code == 0 and self.out_dir and self.out_dir.exists()
        if self.out_dir and self.out_dir.exists():
            self.open_btn.configure(state="normal")
        if self.on_done:
            self.on_done(code)
            return
        if ok:
            if messagebox.askyesno("Clipora Shorts", "숏폼을 다 만들었어요! 결과 폴더를 열까요?"):
                open_folder(self.out_dir)
        else:
            saved = self.save_log()
            messagebox.showerror(
                "Clipora Shorts",
                "만들지 못했어요.\n\n'📋 기록 복사' 버튼을 눌러 기록을 보내 주시면 바로 고칠게요."
                + (f"\n\n기록 파일: {saved}" if saved else ""),
            )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    selftest = "--selftest" in argv
    files = [a for a in argv if not a.startswith("--")]

    def say(msg):
        if selftest:
            sys.__stdout__.buffer.write(f"[selftest] {msg}\n".encode("utf-8", "replace"))
            sys.__stdout__.flush()

    if selftest:
        def watchdog():
            say("timeout: not finished in 4 minutes")
            os._exit(3)

        timer = threading.Timer(240, watchdog)
        timer.daemon = True
        timer.start()
        say(f"python {sys.version.split()[0]}, tk {tk.TkVersion}")

    root = tk.Tk()
    say("Tk() ok")
    result = {"code": None}

    def done(code):
        result["code"] = code
        root.after(200, root.destroy)

    app = App(root, initial=files[0] if files else None, on_done=done if selftest else None, echo=selftest)
    say("window built")
    if selftest:  # 설치 확인용: 창을 띄우고 샘플을 만든 뒤 스스로 닫힘
        root.after(300, lambda: (say("demo started"), app.run(demo=True)))
    root.mainloop()
    if selftest:
        say(f"finished code={result['code']}")
        return result["code"] if result["code"] is not None else 1
    return 0


def safe_main() -> int:
    # pythonw로 실행하면 콘솔이 없어서, 시작 단계 오류를 창으로 보여 줍니다.
    try:
        return main()
    except Exception as e:
        import traceback

        try:
            messagebox.showerror("Clipora Shorts", f"프로그램을 시작하지 못했어요.\n\n{type(e).__name__}: {e}")
        except tk.TclError:
            pass
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(safe_main())
