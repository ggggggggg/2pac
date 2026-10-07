import sys
import time
import sqlite3
from pathlib import Path

# Enable multi-threaded access to SQLite so background data thread can commit results
_orig_sqlite3_connect = sqlite3.connect
def _patched_sqlite3_connect(database, **kwargs):
    kwargs['check_same_thread'] = False
    return _orig_sqlite3_connect(database, **kwargs)
sqlite3.connect = _patched_sqlite3_connect
from PyQt5.QtWidgets import QApplication, QSplashScreen
from PyQt5.QtGui import QPixmap, QColor, QPainter, QFont, QIcon, QPainterPath
from PyQt5.QtCore import Qt, QRectF, QTimer

def create_splash_pixmap(icon_path=None):
    if icon_path is None:
        icon_path = Path(__file__).parent / "adr_gui_icon.png"

    width = 380
    height = 420
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor("#090d16"))
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    
    # Outer Border
    painter.setPen(QColor("#334155"))
    painter.drawRect(0, 0, width - 1, height - 1)
    
    # Inner Card Background
    painter.setBrush(QColor("#111827"))
    painter.drawRoundedRect(10, 10, width - 20, height - 20, 10, 10)
    
    # 2PAC ADR Icon Container
    icon_size = 200
    ix = (width - icon_size) // 2
    iy = 32
    if Path(icon_path).exists():
        path = QPainterPath()
        path.addRoundedRect(ix, iy, icon_size, icon_size, 16, 16)
        painter.save()
        painter.setClipPath(path)
        icon_pix = QPixmap(str(icon_path)).scaled(icon_size, icon_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        painter.drawPixmap(ix, iy, icon_pix)
        painter.restore()

        # Rounded Accent Border around Icon
        painter.setPen(QColor("#38bdf8"))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(ix, iy, icon_size, icon_size, 16, 16)
    
    # Title Text: 2PAC GUI
    painter.setPen(QColor("#f8fafc"))
    title_font = QFont("Inter", 24, QFont.Bold)
    title_font.setStyleHint(QFont.SansSerif)
    painter.setFont(title_font)
    painter.drawText(QRectF(10, 255, width - 20, 42), Qt.AlignCenter, "2PAC GUI")
    
    # Cyan Accent Bar
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#38bdf8"))
    painter.drawRoundedRect(width // 2 - 35, 305, 70, 3, 1, 1)
    
    # Subtitle Text
    painter.setPen(QColor("#94a3b8"))
    sub_font = QFont("Inter", 11)
    painter.setFont(sub_font)
    painter.drawText(QRectF(10, 325, width - 20, 30), Qt.AlignCenter, "Starting telemetry & hardware drivers...")
    
    painter.end()
    return pixmap

def main():
    icon_path = Path(__file__).parent / "adr_gui_icon.png"

    # Set application identity and WM_CLASS so GNOME Shell pairs windows with 2pac_gui.desktop
    sys.argv[0] = "2pac_gui"
    app = QApplication(["2pac_gui"] + sys.argv[1:])
    app.setApplicationName("2pac_gui")
    app.setDesktopFileName("2pac_gui.desktop")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyle('Fusion')
    
    # 2. Show Splash Screen with 2PAC ADR Icon & "2PAC GUI"
    splash_pix = create_splash_pixmap(icon_path)
    splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
    if icon_path.exists():
        splash.setWindowIcon(QIcon(str(icon_path)))
    splash.show()
    app.processEvents()
    
    # Silence loggers
    import logging
    logging.getLogger('qcodes').setLevel(logging.WARNING)
    logging.getLogger('matplotlib').setLevel(logging.WARNING)
    logging.getLogger('matplotlib.font_manager').setLevel(logging.WARNING)
    
    from qcodes.logger import start_all_logging
    start_all_logging()
    app.processEvents()
    
    # 3. Setup Daily Continuous Logging (Partitioned by Day, no fragmented runs)
    from daily_logger import DailyLogManager
    daily_logger = DailyLogManager()
    app.processEvents()

    # 4. Connect Hardware Drivers while keeping Qt responsive
    from station_2pac import get_station
    import states
    from custom_script_loader import load_all_desktop_scripts
    
    st = get_station()
    states.st = st
    app.processEvents()

    from qcodes.parameters import ElapsedTimeParameter
    elapsed_time = ElapsedTimeParameter('elapsed_time')
    states.elapsed_time = elapsed_time

    desktop_states = load_all_desktop_scripts()
    for k, v in desktop_states.items():
        if k not in states.STATES_DICT:
            states.STATES_DICT[k] = v
    app.processEvents()

    from gui import MyApp

    world = states.StationWorld(station=st)
    states.datasaver_global = daily_logger
    world.datasaver = daily_logger

    world._update(states.wait_forever)
    dataset = daily_logger.dataset

    window = MyApp(world, dataset, states.STATES_DICT, daily_logger=daily_logger)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    window.raise_()
    window.activateWindow()
    splash.finish(window)

    # Force window to foreground in X11 / GNOME Mutter over existing active windows (e.g. VSCode)
    def bring_to_front():
        window.setWindowState((window.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        window.raise_()
        window.activateWindow()
        try:
            import Xlib.display, Xlib.X, Xlib.protocol.event
            d = Xlib.display.Display()
            root = d.screen().root
            net_active = d.intern_atom('_NET_ACTIVE_WINDOW')
            ev = Xlib.protocol.event.ClientMessage(
                window=int(window.winId()),
                client_type=net_active,
                data=(32, [2, Xlib.X.CurrentTime, 0, 0, 0])
            )
            root.send_event(ev, event_mask=Xlib.X.SubstructureRedirectMask | Xlib.X.SubstructureNotifyMask)
            d.sync()
        except Exception:
            pass

    bring_to_front()
    QTimer.singleShot(100, bring_to_front)
    QTimer.singleShot(350, bring_to_front)

    ret = app.exec_()
    try:
        daily_logger.close()
    except Exception:
        pass
    sys.exit(ret)

if __name__ == "__main__":
    main()
