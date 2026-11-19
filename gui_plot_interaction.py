"""
Matplotlib mouse interaction: click/drag/scroll zoom, cursor readout.

Mixin for gui.MyApp (split out of gui.py, P1-12). Methods are unchanged; they use the
MyApp instance (self) and the shared names in gui_common.
"""
from gui_common import *  # noqa: F401,F403
from gui_common import _states_mod  # noqa: F401


class PlotInteractionMixin:

    def _find_scroll_axis_and_zone(self, event):
        """
        Determines target axis and zoom zone ('x', 'y', or 'both') based on mouse position.
        Handles event.inaxes as well as hover over axis tick labels outside bounding box.
        """
        if not self.axes_list or event.x is None or event.y is None:
            return None, None

        # 1. If inside an axis bounding box
        if event.inaxes in self.axes_list:
            ax = event.inaxes
            bbox = ax.bbox
            rx = (event.x - bbox.x0) / bbox.width if bbox.width > 0 else 0.5
            ry = (event.y - bbox.y0) / bbox.height if bbox.height > 0 else 0.5
            if ry < 0.25 and rx >= 0.25:
                return ax, "x"
            elif rx < 0.25 and ry >= 0.25:
                return ax, "y"
            elif rx < 0.25 and ry < 0.25:
                return ax, "x" if ry < rx else "y"
            else:
                return ax, "both"

        # 2. If hovering outside bounding box near axis ticks or labels
        for ax in self.axes_list:
            bbox = ax.bbox
            # Hovering near bottom edge (X axis tick numbers / labels)
            if (bbox.x0 - 15 <= event.x <= bbox.x1 + 15) and (bbox.y0 - 45 <= event.y <= bbox.y0 + 5):
                return ax, "x"
            # Hovering near left edge (Y axis tick numbers / labels)
            if (bbox.x0 - 65 <= event.x <= bbox.x0 + 5) and (bbox.y0 - 15 <= event.y <= bbox.y1 + 15):
                return ax, "y"

        # Fallback to first axis X zoom if near the canvas
        return self.axes_list[0], "x"

    def reset_zoom(self):
        self.user_has_zoomed = False
        self._drag_active = False
        self._drag_start_ax = None
        self.update_plot()

    def mpl_on_click(self, event):
        if event.button == 3:  # Right-click resets zoom
            self.reset_zoom()
            return

        if event.button == 1 and event.inaxes in self.axes_list:
            self._drag_active = True
            self._drag_start_x = event.x
            self._drag_start_y = event.y
            self._drag_start_ax = event.inaxes
            self._drag_init_xlim = event.inaxes.get_xlim()
            self._drag_init_ylim = event.inaxes.get_ylim()
            self._drag_has_moved = False

    def mpl_on_release(self, event):
        if event.button == 1:
            if getattr(self, "_drag_has_moved", False):
                if hasattr(self, "_zoom_update_timer"):
                    self._zoom_update_timer.start(10)
            self._drag_active = False
            self._drag_start_ax = None

    def mpl_on_scroll(self, event):
        if not self.axes_list:
            return

        ax, zone = self._find_scroll_axis_and_zone(event)
        if ax is None or zone is None:
            return

        scale_factor = 0.8 if event.button == 'up' else 1.25
        zoom_x = (zone in ("x", "both"))
        zoom_y = (zone in ("y", "both"))

        # Zoom X axis (affects all subplots synchronously)
        if zoom_x:
            cur_xlim = self.axes_list[0].get_xlim()
            span_x = cur_xlim[1] - cur_xlim[0]
            if event.xdata is not None:
                x_center = event.xdata
            else:
                bbox = ax.bbox
                if bbox.width > 0 and bbox.x0 <= event.x <= bbox.x1:
                    frac = (event.x - bbox.x0) / bbox.width
                    x_center = cur_xlim[0] + frac * span_x
                else:
                    x_center = (cur_xlim[0] + cur_xlim[1]) / 2.0

            # Guard against extreme zoom-in (< 1s) or extreme zoom-out (> 50 years)
            MIN_SPAN_X = 1.0  # 1 second
            MAX_SPAN_X = 50.0 * 365.25 * 86400.0  # 50 years

            new_span = span_x * scale_factor
            if scale_factor < 1.0 and span_x <= MIN_SPAN_X:
                new_span = MIN_SPAN_X
            elif scale_factor > 1.0 and span_x >= MAX_SPAN_X:
                new_span = MAX_SPAN_X
            else:
                new_span = max(MIN_SPAN_X, min(MAX_SPAN_X, new_span))

            frac_center = (x_center - cur_xlim[0]) / span_x if span_x > 0 else 0.5
            new_xlim = [x_center - frac_center * new_span,
                        x_center + (1.0 - frac_center) * new_span]
            for a in self.axes_list:
                a.set_xlim(new_xlim)

        # Zoom Y axis (affects target subplot only)
        if zoom_y:
            cur_ylim = ax.get_ylim()
            if ax.get_yscale() == 'log' and cur_ylim[0] > 0 and cur_ylim[1] > 0:
                log_min = np.log10(cur_ylim[0])
                log_max = np.log10(cur_ylim[1])
                span_log = log_max - log_min
                if event.ydata is not None and event.ydata > 0:
                    log_center = np.log10(event.ydata)
                else:
                    bbox = ax.bbox
                    if bbox.height > 0 and bbox.y0 <= event.y <= bbox.y1:
                        frac = (event.y - bbox.y0) / bbox.height
                        log_center = log_min + frac * span_log
                    else:
                        log_center = (log_min + log_max) / 2.0

                new_log_min = log_center - (log_center - log_min) * scale_factor
                new_log_max = log_center + (log_max - log_center) * scale_factor
                new_log_min = max(-10.0, new_log_min)
                new_log_max = min(10.0, new_log_max)
                ax.set_ylim([10 ** new_log_min, 10 ** new_log_max])
            else:
                span_y = cur_ylim[1] - cur_ylim[0]
                if event.ydata is not None:
                    y_center = event.ydata
                else:
                    bbox = ax.bbox
                    if bbox.height > 0 and bbox.y0 <= event.y <= bbox.y1:
                        frac = (event.y - bbox.y0) / bbox.height
                        y_center = cur_ylim[0] + frac * span_y
                    else:
                        y_center = (cur_ylim[0] + cur_ylim[1]) / 2.0

                new_ylim = [y_center - (y_center - cur_ylim[0]) * scale_factor,
                            y_center + (cur_ylim[1] - y_center) * scale_factor]
                ax.set_ylim(new_ylim)

        self.user_has_zoomed = True
        if zoom_x:
            self._update_faa_card_rms_title()
        self.canvas.draw_idle()
        if hasattr(self, "_zoom_update_timer"):
            self._zoom_update_timer.start(25)

    def mpl_on_mouse_move(self, event):
        self.on_mouse_move_event = event

        # Handle left-click dragging and panning
        if self._drag_active and self._drag_start_ax is not None and event.x is not None and event.y is not None:
            dx = event.x - self._drag_start_x
            dy = event.y - self._drag_start_y
            if not self._drag_has_moved and (abs(dx) > 3 or abs(dy) > 3):
                self._drag_has_moved = True
                self.user_has_zoomed = True

            if self._drag_has_moved:
                ax = self._drag_start_ax
                bbox = ax.bbox
                if bbox.width > 0 and bbox.height > 0:
                    # Shift X across all subplots
                    x_min0, x_max0 = self._drag_init_xlim
                    span_x = x_max0 - x_min0
                    shift_x = (dx / bbox.width) * span_x
                    new_xlim = (x_min0 - shift_x, x_max0 - shift_x)
                    for a in self.axes_list:
                        a.set_xlim(new_xlim)

                    # Shift Y for the dragged subplot
                    y_min0, y_max0 = self._drag_init_ylim
                    if ax.get_yscale() == 'log' and y_min0 > 0 and y_max0 > 0:
                        log_min = np.log10(y_min0)
                        log_max = np.log10(y_max0)
                        span_log_y = log_max - log_min
                        shift_log_y = (dy / bbox.height) * span_log_y
                        new_ylim = (10 ** (log_min - shift_log_y), 10 ** (log_max - shift_log_y))
                    else:
                        span_y = y_max0 - y_min0
                        shift_y = (dy / bbox.height) * span_y
                        new_ylim = (y_min0 - shift_y, y_max0 - shift_y)
                    ax.set_ylim(new_ylim)

                    self._update_faa_card_rms_title()
                    self.canvas.draw_idle()

        self._update_cursor_status()
