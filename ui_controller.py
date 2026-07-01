"""
ui_controller.py — Kontrol Antigravity IDE UI via PyAutoGUI
Untuk auto-type pesan ke chat input & copy respons.
Menyimpan dan memuat koordinat kalibrasi secara otomatis dari coords.json.
"""
import time
import threading
import json
import os
import pyautogui
import pygetwindow as gw
import ctypes

# Path file coords
COORDS_FILE = os.path.join(os.path.dirname(__file__), "coords.json")

# Koordinat default
_config = {
    "input_x": None,
    "input_y": None,
    "input_rx": None,
    "input_ry": None,
    "model_x": None,
    "model_y": None,
    "model_rx": None,
    "model_ry": None,
    "calibrated": False,
}

# Lock agar tidak ada race condition saat multi-message
_type_lock = threading.Lock()

# Judul window yang dicari (partial match)
WINDOW_TITLE_KEYWORDS = ["Antigravity", "antigravity"]


def load_coords():
    """Load koordinat dari coords.json jika ada."""
    global _config
    if os.path.exists(COORDS_FILE):
        try:
            with open(COORDS_FILE, "r") as f:
                data = json.load(f)
                _config["input_x"] = data.get("input_x") or data.get("x")
                _config["input_y"] = data.get("input_y") or data.get("y")
                _config["input_rx"] = data.get("input_rx")
                _config["input_ry"] = data.get("input_ry")
                _config["model_x"] = data.get("model_x")
                _config["model_y"] = data.get("model_y")
                _config["model_rx"] = data.get("model_rx")
                _config["model_ry"] = data.get("model_ry")
                _config["calibrated"] = True
                print(f"[UI] Koordinat dimuat: Input({_config['input_x']}, {_config['input_y']}), Model({_config['model_x']}, {_config['model_y']})")
        except Exception as e:
            print(f"[UI] Gagal memuat coords.json: {e}")


def save_coords():
    """Save koordinat ke coords.json."""
    try:
        with open(COORDS_FILE, "w") as f:
            json.dump({
                "input_x": _config["input_x"],
                "input_y": _config["input_y"],
                "input_rx": _config["input_rx"],
                "input_ry": _config["input_ry"],
                "model_x": _config["model_x"],
                "model_y": _config["model_y"],
                "model_rx": _config["model_rx"],
                "model_ry": _config["model_ry"]
            }, f)
    except Exception as e:
        print(f"[UI] Gagal menyimpan coords.json: {e}")


# Load koordinat langsung saat modul di-import
load_coords()


def find_ide_window():
    """Cari window Antigravity IDE. Return window object atau None."""
    all_windows = gw.getAllWindows()
    for w in all_windows:
        for kw in WINDOW_TITLE_KEYWORDS:
            if kw.lower() in w.title.lower():
                return w
    return None


def is_ide_active() -> bool:
    """Cek apakah Antigravity IDE sedang active/focused."""
    try:
        active = gw.getActiveWindow()
        if active is None:
            return False
        return any(kw.lower() in active.title.lower() for kw in WINDOW_TITLE_KEYWORDS)
    except Exception:
        return False


def focus_ide():
    """Bring Antigravity IDE ke foreground."""
    win = find_ide_window()
    if win:
        try:
            win.activate()
            time.sleep(0.3)
            return True
        except Exception:
            pass
    return False


def find_webview_hwnd(parent_hwnd) -> int:
    """Temukan child window WebView2 (Chrome_RenderWidgetHostHWND) di dalam IDE."""
    target_hwnd = [None]
    
    def enum_child_callback(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        class_name = buf.value
        if "RenderWidgetHost" in class_name or "WebView2" in class_name or "Chrome" in class_name:
            target_hwnd[0] = hwnd
            return False  # Berhenti enum jika ketemu
        return True
        
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    ctypes.windll.user32.EnumChildWindows(parent_hwnd, WNDENUMPROC(enum_child_callback), None)
    return target_hwnd[0] or parent_hwnd


def click_coords_background(element_type: str, offset_y: int = 0) -> bool:
    """Kirim klik mouse ke window di background menggunakan WM_LBUTTONDOWN/UP (tanpa gerakin kursor)."""
    win = find_ide_window()
    if not win:
        return False
        
    rx = _config.get(f"{element_type}_rx")
    ry = _config.get(f"{element_type}_ry")
    
    if rx is None or ry is None:
        return False
        
    hwnd = win._hWnd
    target_hwnd = find_webview_hwnd(hwnd)
    
    click_x = rx
    click_y = ry + offset_y
    
    lparam = (click_y << 16) | (click_x & 0xFFFF)
    # WM_LBUTTONDOWN = 0x0201, WM_LBUTTONUP = 0x0202
    ctypes.windll.user32.PostMessageW(target_hwnd, 0x0201, 1, lparam)
    time.sleep(0.05)
    ctypes.windll.user32.PostMessageW(target_hwnd, 0x0202, 0, lparam)
    return True


def click_coords(element_type: str) -> bool:
    """Klik koordinat elemen dengan memprioritaskan posisi relative jika window dipindah-pindah."""
    # Coba kirim klik background terlebih dahulu (Hands-free / tanpa memindahkan mouse cursor!)
    if click_coords_background(element_type):
        return True
        
    # Fallback ke pyautogui jika background click gagal
    win = find_ide_window()
    if not win:
        return False
        
    rx = _config.get(f"{element_type}_rx")
    ry = _config.get(f"{element_type}_ry")
    ax = _config.get(f"{element_type}_x")
    ay = _config.get(f"{element_type}_y")
    
    if rx is not None and ry is not None:
        target_x = win.left + rx
        target_y = win.top + ry
        pyautogui.click(target_x, target_y)
        return True
    elif ax is not None and ay is not None:
        pyautogui.click(ax, ay)
        return True
    return False


def set_input_coords(x: int, y: int):
    """Set koordinat input box (menyimpan absolute & relative ke window)."""
    win = find_ide_window()
    if win:
        _config["input_rx"] = x - win.left
        _config["input_ry"] = y - win.top
    _config["input_x"] = x
    _config["input_y"] = y
    _config["calibrated"] = True
    save_coords()


def set_model_coords(x: int, y: int):
    """Set koordinat model dropdown (menyimpan absolute & relative ke window serta cropping visual)."""
    win = find_ide_window()
    if win:
        _config["model_rx"] = x - win.left
        _config["model_ry"] = y - win.top
    _config["model_x"] = x
    _config["model_y"] = y
    _config["calibrated"] = True
    save_coords()
    
    # Ambil visual template dropdown di sekitar cursor
    calibrate_model_image(x, y)


def calibrate_model_image(x: int, y: int) -> bool:
    """Ambil screenshot kecil (crop) di sekitar koordinat cursor saat kalibrasi model."""
    try:
        # Ambil area 80x30 piksel di sekitar cursor
        left = x - 40
        top = y - 15
        width = 80
        height = 30
        
        screenshot = pyautogui.screenshot(region=(left, top, width, height))
        img_path = os.path.join(os.path.dirname(__file__), "model_dropdown.png")
        screenshot.save(img_path)
        print(f"[UI] Template model dropdown disimpan ke: {img_path}")
        return True
    except Exception as e:
        print(f"[UI] Gagal membuat template gambar: {e}")
        return False


def find_model_dropdown_visually():
    """Cari posisi model dropdown di layar secara visual menggunakan template gambar."""
    img_path = os.path.join(os.path.dirname(__file__), "model_dropdown.png")
    if not os.path.exists(img_path):
        return None
        
    try:
        # Gunakan parameter confidence jika opencv terpasang agar lebih fleksibel
        pos = pyautogui.locateCenterOnScreen(img_path, confidence=0.8)
        if pos:
            return pos.x, pos.y
    except Exception:
        try:
            pos = pyautogui.locateCenterOnScreen(img_path)
            if pos:
                return pos.x, pos.y
        except Exception:
            pass
    return None


def switch_model_in_ide(model_index: int) -> dict:
    """
    Otomatis mengganti model di background (tanpa menggerakkan mouse cursor).
    """
    global _type_lock
    with _type_lock:
        win = find_ide_window()
        if not win:
            return {"success": False, "error": "Window Antigravity tidak ditemukan."}
            
        # 1. Kirim klik ke dropdown model di background
        ok = click_coords_background("model")
        if not ok:
            return {"success": False, "error": "Koordinat model dropdown belum dikalibrasi. Silakan lakukan kalibrasi model dropdown terlebih dahulu."}
            
        time.sleep(0.4)
        
        # 2. Kirim klik ke pilihan model berdasarkan Y-offset di background
        # Standard dropdown options memiliki tinggi ~25px per opsi.
        offset_y = 30 + (model_index * 25)
        click_coords_background("model", offset_y=offset_y)
        time.sleep(0.3)
        
        # 3. Kembalikan fokus ke chat input box di background
        click_coords_background("input")
        
        return {"success": True, "error": None}


def get_current_cursor_pos() -> tuple[int, int]:
    """Return posisi cursor mouse saat ini (untuk kalibrasi)."""
    return pyautogui.position()


def type_message_to_ide(message: str) -> dict:
    """
    Ketik pesan ke input box Antigravity IDE di background (tanpa gerakin cursor).
    """
    with _type_lock:
        win = find_ide_window()
        if not win:
            return {"success": False, "error": "Window Antigravity tidak ditemukan. Pastikan IDE terbuka."}

        hwnd = win._hWnd
        webview_hwnd = find_webview_hwnd(hwnd)

        # 1. Kirim klik background untuk memicu fokus input box chat di IDE
        click_coords_background("input")
        time.sleep(0.15)

        # 2. Kirim karakter demi karakter menggunakan WM_CHAR
        for char in message:
            ctypes.windll.user32.PostMessageW(webview_hwnd, 0x0102, ord(char), 0)
            time.sleep(0.001)

        time.sleep(0.1)

        # 3. Kirim Enter key press (VK_RETURN = 0x0D)
        # WM_KEYDOWN = 0x0100, WM_KEYUP = 0x0101
        ctypes.windll.user32.PostMessageW(webview_hwnd, 0x0100, 0x0D, 0)
        time.sleep(0.02)
        ctypes.windll.user32.PostMessageW(webview_hwnd, 0x0101, 0x0D, 0)

        return {"success": True, "error": None}


def start_calibration_mode() -> dict:
    pos = get_current_cursor_pos()
    return {
        "mode": "calibration",
        "current_pos": pos,
        "instruction": (
            "Mode kalibrasi aktif!\n\n"
            "Dalam 5 detik, arahkan mouse ke input box chat Antigravity."
        )
    }
