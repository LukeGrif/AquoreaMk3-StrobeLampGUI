import socket
import threading
import tkinter as tk
from tkinter import ttk, messagebox

DEFAULT_HOST = "192.168.2.70"
DEFAULT_PORT = 9000

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
        s.settimeout(None)
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
        if not self.sock:
            raise RuntimeError("Not connected")
        data = (text.strip() + "\n").encode()
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
        self.title("Strobe / Lamp Controller (TCP) Mk3 Manual")
        self.geometry("780x560")

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        # Header
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0,8))
        self.logo_img = None
        try:
            self.logo_img = tk.PhotoImage(file="cris_logo.png")
            self.logo_img = self.logo_img.subsample(6, 6)
            ttk.Label(header, image=self.logo_img).pack(side="left")
        except Exception:
            ttk.Label(header, text="CRIS", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(header, text="Strobe & Lamp Controller", font=("Segoe UI", 14)).pack(side="left", padx=10)

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

        # Custom command
        cust = ttk.Frame(root); cust.pack(fill="x", pady=8)
        ttk.Label(cust, text="Custom:").pack(side="left")
        self.cmd_var = tk.StringVar(value="STATUS")
        e = ttk.Entry(cust, textvariable=self.cmd_var)
        e.pack(side="left", fill="x", expand=True, padx=6)
        e.bind("<Return>", lambda _: self.send_cmd(self.cmd_var.get()))
        ttk.Button(cust, text="Send", command=lambda: self.send_cmd(self.cmd_var.get())).pack(side="left")

        # Two text boxes side-by-side: Log (left) and Received (right)
        views = ttk.Frame(root); views.pack(fill="both", expand=True, pady=8)
        # Left: Log
        log_frame = ttk.LabelFrame(views, text="Log")
        log_frame.pack(side="left", fill="both", expand=True, padx=(0,6))
        self.log = tk.Text(log_frame, height=14, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)
        log_btns = ttk.Frame(log_frame); log_btns.pack(fill="x")
        ttk.Button(log_btns, text="Clear log", command=self.clear_log).pack(side="right", padx=4, pady=4)

        # Right: Received data
        rx_frame = ttk.LabelFrame(views, text="Received data")
        rx_frame.pack(side="left", fill="both", expand=True, padx=(6,0))
        self.rx = tk.Text(rx_frame, height=14, state="disabled", wrap="word")
        self.rx.pack(fill="both", expand=True)
        rx_btns = ttk.Frame(rx_frame); rx_btns.pack(fill="x")
        ttk.Button(rx_btns, text="Clear received", command=self.clear_rx).pack(side="right", padx=4, pady=4)

        self.client = TcpClient(self.on_line_received)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

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

    def _extract_rx_payload(self, line: str) -> str | None:
        """
        Return just the RS485 device payload, or None if the line
        is not an RS485 line.
        """
        if line.startswith("RS485: "):
            return line[7:]
        tag = "[RS485<-] "
        if line.startswith(tag):
            return line[len(tag):]
        return None  # ignore all other messages

    def on_line_received(self, line):
        def ui():
            # Always log everything
            self.append_log(f"<< {line}")
            # Only append to Received box if it's RS485 payload
            payload = self._extract_rx_payload(line)
            if payload:
                self.append_rx(payload)

        self.after(0, ui)

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

    def send_cmd(self, s):
        try:
            self.client.send_line(s)
            self.append_log(f">> {s}")
        except Exception as e:
            messagebox.showwarning("Send failed", str(e))

    def on_close(self):
        self.client.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
