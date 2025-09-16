import os
import sys
import subprocess
import socket
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import csv
import datetime
import time
import re
from pathlib import Path

DEFAULT_HOST = "192.168.2.70"
DEFAULT_PORT = 9000
MANUAL_FILENAME = "Aquorea Mk3 Manual.pdf"  # put this PDF next to main.py

# >>> Set your Sony SDK image folder here (or use the Browse button in the UI)
DEFAULT_IMAGE_DIR = r"C:\Users\Luke Griffin\OneDrive\Desktop\Sony_SDK\build\Release"  # <-- change to your path (Windows example)

# how long we allow between an exposure and its matching image (seconds)
MATCH_TOLERANCE_SEC = 2.0

IMAGE_PATTERN = re.compile(r"^DSC\d{1,}\.(jpg)$", re.IGNORECASE)

def resource_path(rel_path: str) -> str:
    """Return absolute path to resource, works for dev and PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.join(os.path.abspath("."), rel_path)

def open_file_with_default_app(path: str):
    """Open a file with the OS default application."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])

class TcpClient:
    def __init__(self, on_line):
        self.sock = None
        self.alive = False
        self.rx_thread = None
        self.on_line = on_line

    def connect(self, host, port):
        self.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((host, port))
        s.settimeout(None)  # blocking recv
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass
        self.sock = s
        self.alive = True
        self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self.rx_thread.start()

    def _rx_loop(self):
        buf = b""
        try:
            while self.alive:
                data = self.sock.recv(1024)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        self.on_line(line.decode(errors="ignore").strip())
                    except Exception:
                        pass
        except Exception as e:
            self.on_line(f"[RX ERROR] {e}")
        finally:
            self.alive = False
            try: self.sock.close()
            except: pass
            self.sock = None
            self.on_line("[Disconnected]")

    def send_line(self, text: str):
        """
        Send EXACT text as typed. We do NOT strip or uppercase it.
        We only ensure a single trailing newline if one isn't present.
        """
        if not self.sock:
            raise RuntimeError("Not connected")
        if text.endswith("\n"):
            data = text.encode()
        else:
            data = (text + "\n").encode()
        self.sock.sendall(data)

    def close(self):
        self.alive = False
        if self.sock:
            try: self.sock.shutdown(socket.SHUT_RDWR)
            except: pass
            try: self.sock.close()
            except: pass
        self.sock = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Strobe / Lamp Controller (TCP) Aquorea Mk3")
        self.geometry("940x650")

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        # Header
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0,8))
        self.logo_img = None
        try:
            logo_path = resource_path("cris_logo.png")
            self.logo_img = tk.PhotoImage(file=logo_path)
            self.logo_img = self.logo_img.subsample(6, 6)
            ttk.Label(header, image=self.logo_img).pack(side="left")
        except Exception:
            ttk.Label(header, text="CRIS", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(header, text="Strobe & Lamp Controller", font=("Segoe UI", 14)).pack(side="left", padx=10)
        ttk.Button(header, text="Open Manual (PDF)", command=self.open_manual).pack(side="right")

        # Connection row
        row = ttk.Frame(root); row.pack(fill="x", pady=4)
        ttk.Label(row, text="IP:").pack(side="left")
        self.ip_var = tk.StringVar(value=DEFAULT_HOST)
        ttk.Entry(row, textvariable=self.ip_var, width=18).pack(side="left", padx=5)
        ttk.Label(row, text="Port:").pack(side="left")
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        ttk.Entry(row, textvariable=self.port_var, width=8).pack(side="left", padx=5)
        ttk.Button(row, text="Connect", command=self.on_connect).pack(side="left", padx=6)
        ttk.Button(row, text="Disconnect", command=self.on_disconnect).pack(side="left")

        # Image folder picker
        img_row = ttk.Frame(root); img_row.pack(fill="x", pady=4)
        ttk.Label(img_row, text="Image folder:").pack(side="left")
        self.image_dir_var = tk.StringVar(value=DEFAULT_IMAGE_DIR)
        ttk.Entry(img_row, textvariable=self.image_dir_var, width=60).pack(side="left", padx=5)
        ttk.Button(img_row, text="Browse…", command=self.browse_image_dir).pack(side="left")

        # Sliders
        sliders = ttk.LabelFrame(root, text="Intensities")
        sliders.pack(fill="x", pady=10)

        srow = ttk.Frame(sliders); srow.pack(fill="x", pady=6)
        ttk.Label(srow, text="Strobe intensity").pack(side="left")
        self.strobe_scale = ttk.Scale(srow, from_=0, to=100, orient="horizontal",
                                      command=lambda v: self._update_val(self.lbl_strobe, v))
        self.strobe_scale.pack(side="left", fill="x", expand=True, padx=10)
        self.lbl_strobe = ttk.Label(srow, width=4, anchor="e", text="0"); self.lbl_strobe.pack(side="left")
        self.strobe_scale.bind("<ButtonRelease-1>", lambda e: self.send_cmd(f"STROBE_INTENSITY {int(float(self.strobe_scale.get()))}"))

        lrow = ttk.Frame(sliders); lrow.pack(fill="x", pady=6)
        ttk.Label(lrow, text="Lamp intensity").pack(side="left")
        self.lamp_scale = ttk.Scale(lrow, from_=0, to=100, orient="horizontal",
                                    command=lambda v: self._update_val(self.lbl_lamp, v))
        self.lamp_scale.pack(side="left", fill="x", expand=True, padx=10)
        self.lbl_lamp = ttk.Label(lrow, width=4, anchor="e", text="0"); self.lbl_lamp.pack(side="left")
        self.lamp_scale.bind("<ButtonRelease-1>", lambda e: self.send_cmd(f"LAMP_INTENSITY {int(float(self.lamp_scale.get()))}"))

        # Lamp controls + Status
        lamp_ctrl = ttk.Frame(root); lamp_ctrl.pack(fill="x", pady=6)
        ttk.Button(lamp_ctrl, text="Lamp OFF", command=lambda: self.send_cmd("LAMP OFF")).pack(side="left", padx=5)
        ttk.Button(lamp_ctrl, text="Status",   command=lambda: self.send_cmd("STATUS")).pack(side="left", padx=10)

        # Exposure counter controls
        exp_ctrl = ttk.LabelFrame(root, text="Exposure Counter")
        exp_ctrl.pack(fill="x", pady=10)
        ttk.Button(exp_ctrl, text="Start Count", command=self.start_exposure_count).pack(side="left", padx=5)
        ttk.Button(exp_ctrl, text="Stop Count", command=self.stop_exposure_count).pack(side="left", padx=5)
        ttk.Label(exp_ctrl, text="Count:").pack(side="left", padx=(20,5))
        self.exposure_var = tk.StringVar(value="0")
        self.exposure_lbl = ttk.Label(exp_ctrl, textvariable=self.exposure_var, width=10)
        self.exposure_lbl.pack(side="left")
        ttk.Button(exp_ctrl, text="Open CSV", command=self.open_current_csv).pack(side="left", padx=20)

        # Custom command (RAW — exact text)
        cust = ttk.Frame(root); cust.pack(fill="x", pady=8)
        ttk.Label(cust, text="Custom:").pack(side="left")
        self.cmd_var = tk.StringVar(value="~COMMAND|SUBC24991")
        e = ttk.Entry(cust, textvariable=self.cmd_var)
        e.pack(side="left", fill="x", expand=True, padx=6)
        e.bind("<Return>", lambda _: self.send_raw())
        ttk.Button(cust, text="Send", command=self.send_raw).pack(side="left")

        # Two text boxes: Log (left) and Received (right)
        views = ttk.Frame(root); views.pack(fill="both", expand=True, pady=8)
        # Left: Log
        log_frame = ttk.LabelFrame(views, text="Log")
        log_frame.pack(side="left", fill="both", expand=True, padx=(0,6))
        self.log = tk.Text(log_frame, height=16, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)
        log_btns = ttk.Frame(log_frame); log_btns.pack(fill="x")
        ttk.Button(log_btns, text="Clear log", command=self.clear_log).pack(side="right", padx=4, pady=4)

        # Right: Received data
        rx_frame = ttk.LabelFrame(views, text="Received data")
        rx_frame.pack(side="left", fill="both", expand=True, padx=(6,0))
        self.rx = tk.Text(rx_frame, height=16, state="disabled", wrap="word")
        self.rx.pack(fill="both", expand=True)
        rx_btns = ttk.Frame(rx_frame); rx_btns.pack(fill="x")
        ttk.Button(rx_btns, text="Clear received", command=self.clear_rx).pack(side="right", padx=4, pady=4)

        self.client = TcpClient(self.on_line_received)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # exposure / CSV state
        self.polling_active = False
        self.csv_filename = None
        self.last_logged_count = None

        # image pairing state
        self.image_scan_running = False
        self.seen_images = set()          # filenames seen this run
        self.pending_exposures = []       # [(ts_datetime, count)]
        self.pending_images = []          # [(ts_datetime, filename)]
        self.run_start_time = None        # ignore images older than this

    # ---------- Manual open ----------
    def open_manual(self):
        path = resource_path(MANUAL_FILENAME)
        if not os.path.exists(path):
            messagebox.showerror("Manual not found", f"Couldn't find:\n{path}")
            return
        try:
            open_file_with_default_app(path)
        except Exception as e:
            messagebox.showerror("Error opening manual", str(e))

    # ---------- UI helpers ----------
    def browse_image_dir(self):
        d = filedialog.askdirectory(initialdir=self.image_dir_var.get() or os.getcwd(),
                                    title="Select image folder (Sony SDK output)")
        if d:
            self.image_dir_var.set(d)

    def _update_val(self, label, v):
        try:
            label.config(text=str(int(float(v))))
        except:
            pass

    def append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def append_rx(self, text):
        self.rx.configure(state="normal")
        self.rx.insert("end", text + "\n")
        self.rx.see("end")
        self.rx.configure(state="disabled")

    def clear_rx(self):
        self.rx.configure(state="normal")
        self.rx.delete("1.0", "end")
        self.rx.configure(state="disabled")

    def _extract_rx_payload(self, line: str):
        if line.startswith("RS485: "):
            return line[7:]
        tag = "[RS485<-] "
        if line.startswith(tag):
            return line[len(tag):]
        return None

    # ---------- Incoming TCP lines ----------
    def on_line_received(self, line):
        def ui():
            self.append_log(f"<< {line}")
            payload = self._extract_rx_payload(line)
            if payload:
                self.append_rx(payload)

            # Exposure count handling
            if line.startswith("EXPOSURE_COUNT "):
                try:
                    val = int(line.split()[1])
                    # Only act on increases
                    if self.last_logged_count is None or val != self.last_logged_count:
                        self.last_logged_count = val
                        self.exposure_var.set(str(val))
                        exp_ts = datetime.datetime.now()

                        # record as pending exposure for pairing
                        self.pending_exposures.append((exp_ts, val))

                        # If CSV exists but header not yet written (should be), ensure header
                        if self.csv_filename and not Path(self.csv_filename).exists():
                            with open(self.csv_filename, "w", newline="") as f:
                                csv.writer(f).writerow(["ExposureTS","ExposureCount","ImageTS","ImageFile","Delta_ms"])

                        # Try to match right away with any pending images
                        self.try_match_pairs()
                except Exception as e:
                    self.append_log(f"[CSV/Pair ERROR] {e}")
        self.after(0, ui)

    # ---------- Connect / Disconnect ----------
    def on_connect(self):
        host = self.ip_var.get().strip()
        try:
            port = int(self.port_var.get())
            self.client.connect(host, port)
            self.append_log(f"[Connected to {host}:{port}]")
        except Exception as e:
            messagebox.showerror("Connect failed", str(e))

    def on_disconnect(self):
        self.client.close()
        self.append_log("[Disconnected]")

    # ---------- Sending ----------
    def send_cmd(self, s):
        try:
            self.client.send_line(s)
            self.append_log(f">> {s}")
        except Exception as e:
            messagebox.showwarning("Send failed", str(e))

    def send_raw(self):
        try:
            text = self.cmd_var.get()
            self.client.send_line(text)
            self.append_log(f">> {text}")
        except Exception as e:
            messagebox.showwarning("Send failed", str(e))

    # ---------- Exposure controls ----------
    def start_exposure_count(self):
        # Prepare CSV (new file each run)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.csv_filename = f"exposure_log_{ts}.csv"
        try:
            with open(self.csv_filename, "w", newline="") as f:
                csv.writer(f).writerow(["ExposureTS","ExposureCount","ImageTS","ImageFile","Delta_ms"])
            self.append_log(f"[CSV] Logging exposures to {self.csv_filename}")
        except Exception as e:
            self.append_log(f"[CSV ERROR] {e}")

        # Reset pairing state
        self.pending_exposures.clear()
        self.pending_images.clear()
        self.seen_images.clear()
        self.run_start_time = datetime.datetime.now()

        # Snapshot existing files so we only pick up new ones
        self.snapshot_existing_images()

        # Start polling exposure count + image folder scan
        self.polling_active = True
        self.last_logged_count = None
        self.send_cmd("START_EXPOSURE_COUNT")
        self.poll_exposure_count()
        if not self.image_scan_running:
            self.image_scan_running = True
            self.after(300, self.scan_image_folder)

    def stop_exposure_count(self):
        self.send_cmd("STOP_EXPOSURE_COUNT")
        self.polling_active = False
        self.append_log("[CSV] Exposure logging stopped")

    def poll_exposure_count(self):
        if not self.polling_active:
            return
        try:
            self.client.send_line("GET_EXPOSURE_COUNT")
        except Exception:
            return
        self.after(500, self.poll_exposure_count)

    # ---------- Image monitoring & pairing ----------
    def snapshot_existing_images(self):
        folder = Path(self.image_dir_var.get())
        try:
            if not folder.exists():
                self.append_log(f"[IMG] Folder not found: {folder}")
                return
            for p in folder.iterdir():
                if p.is_file() and IMAGE_PATTERN.match(p.name):
                    self.seen_images.add(p.name)
        except Exception as e:
            self.append_log(f"[IMG SNAPSHOT ERROR] {e}")

    def scan_image_folder(self):
        """Poll the folder for new DSC* files; enqueue with mtime; try matching."""
        folder = Path(self.image_dir_var.get())
        if not self.image_scan_running:
            return
        try:
            if folder.exists():
                for p in folder.iterdir():
                    if not p.is_file():
                        continue
                    name = p.name
                    if name in self.seen_images:
                        continue
                    if not IMAGE_PATTERN.match(name):
                        continue

                    # Only consider files newer than run start (avoid old backlog)
                    try:
                        mtime = datetime.datetime.fromtimestamp(p.stat().st_mtime)
                    except Exception:
                        continue
                    if self.run_start_time and mtime < self.run_start_time - datetime.timedelta(seconds=1):
                        # mark seen but ignore (old)
                        self.seen_images.add(name)
                        continue

                    # New image discovered
                    self.seen_images.add(name)
                    self.pending_images.append((mtime, name))
                    self.append_log(f"[IMG] New file: {name} @ {mtime.strftime('%H:%M:%S.%f')[:-3]}")

                # attempt matches whenever we add images
                self.try_match_pairs()

        except Exception as e:
            self.append_log(f"[IMG SCAN ERROR] {e}")

        # reschedule scan
        self.after(300, self.scan_image_folder)

    def try_match_pairs(self):
        """Greedy match: for each exposure (oldest first), pick the closest-time unmatched image within tolerance."""
        if not self.csv_filename:
            return
        if not self.pending_exposures or not self.pending_images:
            return

        # sort by time
        self.pending_exposures.sort(key=lambda x: x[0])
        self.pending_images.sort(key=lambda x: x[0])

        matched_exposures = []
        matched_images_idx = set()

        for ei, (ets, ecount) in enumerate(self.pending_exposures):
            # find image with minimal |t_img - t_exp|
            best_idx = None
            best_dt = None
            for ii, (its, fname) in enumerate(self.pending_images):
                if ii in matched_images_idx:
                    continue
                dt = abs((its - ets).total_seconds())
                if best_dt is None or dt < best_dt:
                    best_dt = dt
                    best_idx = ii
            if best_idx is not None and best_dt is not None and best_dt <= MATCH_TOLERANCE_SEC:
                matched_exposures.append(ei)
                matched_images_idx.add(best_idx)

        # write matches to CSV
        if matched_exposures:
            with open(self.csv_filename, "a", newline="") as f:
                writer = csv.writer(f)
                for ei in sorted(matched_exposures, reverse=True):
                    ets, ecount = self.pending_exposures[ei]
                    # find its paired image again (closest within tolerance)
                    best_idx = None
                    best_dt = None
                    for ii, (its, fname) in enumerate(self.pending_images):
                        if ii in matched_images_idx:
                            # may include many; pick the one closest
                            pass
                    # Recompute for certainty (closest)
                    best_idx2 = None
                    best_dt2 = None
                    for ii, (its, fname) in enumerate(self.pending_images):
                        if ii not in matched_images_idx:
                            continue
                        dt = abs((its - ets).total_seconds())
                        if best_dt2 is None or dt < best_dt2:
                            best_dt2 = dt
                            best_idx2 = ii
                    # Fallback: if not found above (shouldn't happen), pick closest overall within tol
                    if best_idx2 is None:
                        for ii, (its, fname) in enumerate(self.pending_images):
                            dt = abs((its - ets).total_seconds())
                            if best_dt2 is None or dt < best_dt2:
                                best_dt2 = dt
                                best_idx2 = ii

                    if best_idx2 is not None and best_dt2 is not None and best_dt2 <= MATCH_TOLERANCE_SEC:
                        its, fname = self.pending_images[best_idx2]
                        delta_ms = int(round((its - ets).total_seconds() * 1000.0))
                        writer.writerow([
                            ets.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                            ecount,
                            its.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                            fname,
                            delta_ms
                        ])
                        self.append_log(f"[PAIR] Exposure #{ecount} @ {ets.strftime('%H:%M:%S.%f')[:-3]}  <->  {fname} @ {its.strftime('%H:%M:%S.%f')[:-3]}  (Δ {delta_ms} ms)")

                        # remove matched image & exposure
                        try:
                            self.pending_images.pop(best_idx2)
                        except Exception:
                            pass
                        self.pending_exposures.pop(ei)

        # Keep unmatched items for later scans/updates

    # ---------- Open CSV ----------
    def open_current_csv(self):
        if not self.csv_filename:
            messagebox.showinfo("CSV", "No CSV for this run yet. Press 'Start Count' first.")
            return
        try:
            open_file_with_default_app(self.csv_filename)
        except Exception as e:
            messagebox.showerror("Open CSV failed", str(e))

    # ---------- Close ----------
    def on_close(self):
        self.image_scan_running = False
        self.client.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
