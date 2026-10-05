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
from PyQt5.QtGui import QPixmap, QColor, QPainter, QFont, QIcon
from PyQt5.QtCore import Qt, QRectF, QTimer

def create_splash_pixmap():
    pixmap = QPixmap(440, 200)
    pixmap.fill(QColor("#090d16"))
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    
    # Outer Border
    painter.setPen(QColor("#334155"))
    painter.drawRect(0, 0, 439, 199)
    
    # Inner Card Background
    painter.setBrush(QColor("#111827"))
    painter.drawRoundedRect(10, 10, 419, 179, 6, 6)
    
    # Header Accent line
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#38bdf8"))
    painter.drawRoundedRect(25, 25, 390, 4, 2, 2)
    
    # Title Text
    painter.setPen(QColor("#38bdf8"))
    title_font = QFont("Inter", 22, QFont.Bold)
    title_font.setStyleHint(QFont.SansSerif)
    painter.setFont(title_font)
    painter.drawText(QRectF(20, 45, 400, 45), Qt.AlignCenter, "2pac gui")
    
    # Subtitle Text
    painter.setPen(QColor("#94a3b8"))
    sub_font = QFont("Inter", 11)
    painter.setFont(sub_font)
    painter.drawText(QRectF(20, 100, 400, 30), Qt.AlignCenter, "Starting telemetry & hardware drivers...")
    
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
    
    # 2. Show Splash Screen with "2pac gui"
    splash_pix = create_splash_pixmap()
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
    
    # 3. Setup Database
    import qcodes
    from qcodes import initialise_or_create_database_at, load_or_create_experiment, Measurement
    from qcodes.parameters import ElapsedTimeParameter
    from datetime import datetime
    
    today = datetime.now().strftime("%Y-%m-%d")
    db_dir = Path.home() / "2pac_logs" / today
    db_dir.mkdir(parents=True, exist_ok=True)
    db_file_path = db_dir / "2pac.db"
    initialise_or_create_database_at(str(db_file_path))
    app.processEvents()
    
    exp = load_or_create_experiment(
        experiment_name='running 2pac adr',
        sample_name="no sample"
    )
    app.processEvents()

    # 4. Connect Hardware Drivers while keeping Qt responsive
    from station_2pac import get_station
    import states
    from custom_script_loader import load_all_desktop_scripts
    
    st = get_station()
    states.st = st
    app.processEvents()

    elapsed_time = ElapsedTimeParameter('elapsed_time')
    states.elapsed_time = elapsed_time

    meas = Measurement(exp=exp, name='adr run', station=st)
    meas.register_parameter(elapsed_time)
    meas.register_parameter(st.cryocon.chA_temperature, setpoints=[elapsed_time])
    meas.register_parameter(st.cryocon.chB_temperature, setpoints=[elapsed_time])
    meas.register_parameter(st.cryocon.chC_temperature, setpoints=[elapsed_time])
    meas.register_parameter(st.cryocon.chD_temperature, setpoints=[elapsed_time])
    meas.register_parameter(st.labjack.kepco_current, setpoints=[elapsed_time])
    meas.register_parameter(st.labjack.kepco_voltage)
    meas.register_parameter(st.ls370.heater.out, setpoints=[elapsed_time])
    meas.register_parameter(st.labjack.relay, paramtype="text")
    meas.register_parameter(st.labjack.heatswitch_adr, paramtype="text")
    meas.register_parameter(st.labjack.heatswitch_charcoal, paramtype="text")
    meas.register_parameter(st.labjack.heatswitch_pot, paramtype="text")
    meas.register_parameter(st.labjack.he3_pressure, setpoints=[elapsed_time])
    meas.register_custom_parameter("state", paramtype="text")
    meas.register_custom_parameter("faa_temperature", unit="K", setpoints=[elapsed_time])
    meas.register_custom_parameter("time", unit="s")
    app.processEvents()

    desktop_states = load_all_desktop_scripts()
    states.STATES_DICT.update(desktop_states)
    app.processEvents()

    from gui import MyApp

    # Start in wait_forever writing data continuously
    with meas.run() as datasaver:
        world = states.StationWorld(station=st)
        states.datasaver_global = datasaver
        world.datasaver = datasaver

        world._update(states.wait_forever)
        dataset = datasaver.dataset

        window = MyApp(world, dataset, states.STATES_DICT)
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

        sys.exit(app.exec_())

if __name__ == "__main__":
    main()
