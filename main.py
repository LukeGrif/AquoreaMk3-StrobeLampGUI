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
        # short timeout only for the connect call
        s.settimeout(3)
        s.connect((host, port))
        # after connect: NO timeout for recv (blocking)
        s.settimeout(None)
        # optional keepalive
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
                data = self.sock.recv(1024)  # blocking; no timeout now
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
        self.title("Strobe / Lamp Controller (TCP)")
        self.geometry("660x460")

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        # Header with logo
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0,8))
        # load cris.png from same folder (Tk PhotoImage supports PNG on Tk>=8.6)
        self.logo_img = None
        try:
            self.logo_img = tk.PhotoImage(file="cris_logo.png")
            self.logo_img = self.logo_img.subsample(6, 6)  # shrink by factor 4
            ttk.Label(header, image=self.logo_img).pack(side="left")
        except Exception as e:
            ttk.Label(header, text="CRIS", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(header, text="Strobe & Lamp Controller", font=("Segoe UI", 14)).pack(side="left", padx=10)

        # Connection row
        row = ttk.Frame(root)
        row.pack(fill="x", pady=4)
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

        # Strobe intensity (0..100)
        srow = ttk.Frame(sliders); srow.pack(fill="x", pady=6)
        ttk.Label(srow, text="Strobe intensity").pack(side="left")
        self.strobe_scale = ttk.Scale(srow, from_=0, to=100, orient="horizontal",
                                      command=lambda v: self._update_val(self.lbl_strobe, v))
        self.strobe_scale.pack(side="left", fill="x", expand=True, padx=10)
        self.lbl_strobe = ttk.Label(srow, width=4, anchor="e", text="0"); self.lbl_strobe.pack(side="left")
        self.strobe_scale.bind("<ButtonRelease-1>", lambda e: self.send_cmd(f"STROBE_INTENSITY {int(float(self.strobe_scale.get()))}"))

        # Lamp intensity (0..100)
        lrow = ttk.Frame(sliders); lrow.pack(fill="x", pady=6)
        ttk.Label(lrow, text="Lamp intensity").pack(side="left")
        self.lamp_scale = ttk.Scale(lrow, from_=0, to=100, orient="horizontal",
                                    command=lambda v: self._update_val(self.lbl_lamp, v))
        self.lamp_scale.pack(side="left", fill="x", expand=True, padx=10)
        self.lbl_lamp = ttk.Label(lrow, width=4, anchor="e", text="0"); self.lbl_lamp.pack(side="left")
        self.lamp_scale.bind("<ButtonRelease-1>", lambda e: self.send_cmd(f"LAMP_INTENSITY {int(float(self.lamp_scale.get()))}"))

        # Lamp controls
        lamp_ctrl = ttk.Frame(root); lamp_ctrl.pack(fill="x", pady=6)
        ttk.Button(lamp_ctrl, text="Lamp ON",  command=lambda: self.send_cmd("LAMP ON")).pack(side="left", padx=5)
        ttk.Button(lamp_ctrl, text="Lamp OFF", command=lambda: self.send_cmd("LAMP OFF")).pack(side="left", padx=5)

        # Status button
        ttk.Button(lamp_ctrl, text="Status", command=lambda: self.send_cmd("STATUS")).pack(side="left", padx=10)

        # Custom command row
        cust = ttk.Frame(root);
        cust.pack(fill="x", pady=8)
        ttk.Label(cust, text="Custom:").pack(side="left")
        self.cmd_var = tk.StringVar(value="STATUS")
        e = ttk.Entry(cust, textvariable=self.cmd_var)
        e.pack(side="left", fill="x", expand=True, padx=6)
        e.bind("<Return>", lambda _: self.send_cmd(self.cmd_var.get()))
        ttk.Button(cust, text="Send", command=lambda: self.send_cmd(self.cmd_var.get())).pack(side="left")

        # Log
        self.log = tk.Text(root, height=12, state="disabled")
        self.log.pack(fill="both", expand=True, pady=8)

        self.client = TcpClient(self.on_line_received)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _update_val(self, label, v):
        try: label.config(text=str(int(float(v))))
        except: pass

    def append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def on_line_received(self, line):
        self.after(0, lambda: self.append_log(f"<< {line}"))

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
