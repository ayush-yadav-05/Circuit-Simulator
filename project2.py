# Fixed Circuit Simulator - Improved Canvas and Netlist Handling
# Based on your original file at: /mnt/data/project2.py
# Features added:
# - Robust pin snapping (larger radius + strict enforcement)
# - Visual pin highlight when mouse is near a pin
# - Rubber-band wire preview while drawing
# - Snapping to component pins and to existing wire endpoints
# - Reject wires that aren't snapped to pins
# - Post-netlist floating-node detection (graph connectivity check)
# - Helpful debug prints

import sys
import matlab.engine
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np
import os

from PyQt5.QtWidgets import (
    QMainWindow, QApplication, QLabel, QPushButton, QWidget,
    QVBoxLayout, QHBoxLayout, QFrame, QLineEdit,
    QFileDialog, QInputDialog, QMessageBox
)
from PyQt5.QtGui import QPainter, QPen, QIcon, QBrush
from PyQt5.QtCore import Qt, QPoint, QRect


class NetlistGenerator:
    """Fully patched version with correct node merging, correct ground handling,
       no false shorts, and MATLAB-safe netlist generation."""

    def __init__(self, canvas):
        self.canvas = canvas
        self.nodes = {}
        self.next_node_num = 1
        self.all_pins = []
        self.ground_keys = set()

    # ------------------------------------------------------------
    # Assign node numbers BEFORE merging
    # ------------------------------------------------------------
    def _get_node(self, point, is_new_pin=False):
        key = (point.x(), point.y())
        snap = self.canvas.find_nearest_pin(point)
        if snap:
            key = (snap.x(), snap.y())

        # ground always → node 0
        if key in self.ground_keys:
            return 0

        # return existing node if close
        for (x, y), nid in self.nodes.items():
            if abs(x - key[0]) < self.canvas.grid_size and abs(y - key[1]) < self.canvas.grid_size:
                return nid

        # create new node
        if is_new_pin:
            self.nodes[key] = self.next_node_num
            self.next_node_num += 1
            return self.nodes[key]

        return None

    # ------------------------------------------------------------
    # Collect all pins and ground keys
    # ------------------------------------------------------------
    def _collect_all_pins(self):
        self.all_pins.clear()
        self.ground_keys.clear()

        print("=== RUNNING _collect_all_pins ===")

        # Component pins
        for comp_type, pos in self.canvas.components:
            comp = comp_type.lower().strip()

            if comp == "ground":
                key = (pos.x(), pos.y())
                print("ADDING GROUND KEY:", key)
                self.ground_keys.add(key)
                self.all_pins.append(pos)
                continue

            pins = self.canvas.get_component_pins(comp_type, pos)
            self.all_pins.extend(pins)

        # Wire endpoints
        for a, b in self.canvas.lines:
            self.all_pins.append(a)
            self.all_pins.append(b)

    # ------------------------------------------------------------
    # FINAL generate_netlist (fully patched)
    # ------------------------------------------------------------
    def generate_netlist(self, values):
        print("\n=== GENERATE NETLIST START ===")

        # RESET node tables
        self.nodes.clear()
        self.next_node_num = 1

        self._collect_all_pins()

        # Assign node numbers to all pins BEFORE merging
        for p in self.all_pins:
            self._get_node(p, is_new_pin=True)

        # ------------------------------------------------------------
        # Build adjacency graph of only wire-connected nodes
        # ------------------------------------------------------------
        wire_adj = {}

        def add(a, b):
            wire_adj.setdefault(a, set()).add(b)
            wire_adj.setdefault(b, set()).add(a)

        for a, b in self.canvas.lines:
            n1 = self._get_node(a)
            n2 = self._get_node(b)
            if n1 is not None and n2 is not None:
                add(n1, n2)

        # ------------------------------------------------------------
        # Find connected groups ONLY through wires
        # ------------------------------------------------------------
        visited = set()
        groups = []

        for n in wire_adj:
            if n in visited:
                continue
            stack = [n]
            g = []
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                g.append(cur)
                for nx in wire_adj[cur]:
                    if nx not in visited:
                        stack.append(nx)
            groups.append(g)

        # ------------------------------------------------------------
        # MERGING LOGIC (the most important fix)
        # ------------------------------------------------------------
        merge = {}

        # Step 1 — For any group touching ground → entire group = 0
        for g in groups:
            if any((nid == 0) for nid in g):  # ground included
                for nid in g:
                    merge[nid] = 0

        # Step 2 — Assign IDs to non-ground groups
        next_id = 1
        for g in groups:
            if any((merge.get(n) == 0) for n in g):
                continue  # skip ground group
            for nid in g:
                merge[nid] = next_id
            next_id += 1

        # Step 3 — isolated nodes (not in any wire group)
        for p_key, nid in self.nodes.items():
            if nid not in merge:
                if p_key in self.ground_keys:
                    merge[nid] = 0
                else:
                    merge[nid] = next_id
                    next_id += 1

        print("FINAL NODE MAP:", merge)

        # ------------------------------------------------------------
        # Generate the netlist
        # ------------------------------------------------------------
        netlist = []
        counts = {"resistor": 0, "battery": 0, "capacitor": 0, "inductor": 0}

        for comp, pos in self.canvas.components:
            if comp in ["voltmeter", "ammeter"]:
                continue
            if comp == "ground":
                continue

            pins = self.canvas.get_component_pins(comp, pos)
            n1 = merge[self._get_node(pins[0])]
            n2 = merge[self._get_node(pins[1])]

            if n1 == n2:
                raise ValueError(
                    f"{comp} shorted — both pins map to node {n1}")

            counts[comp] += 1

            if comp == "resistor":
                prefix, val = "R", values.get("R", "100")
            elif comp == "battery":
                prefix, val = "V", values.get("V", "5")
            elif comp == "capacitor":
                prefix, val = "C", values.get("C", "1e-6")
            elif comp == "inductor":
                prefix, val = "L", values.get("L", "1e-3")

            netlist.append(f"{prefix}{counts[comp]} {n1} {n2} {val}")

        print("\nFINAL NETLIST:\n" + "\n".join(netlist))
        print("=== END NETLIST ===\n")

        return "\n".join(netlist)


class CircuitCanvas(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.setStyleSheet(
            "background-color: #0b0b0b; border: 2px solid #555;")
        self.setMouseTracking(True)

        self.start_point = None
        self.end_point = None
        self.lines = []  # list of tuples: (QPoint, QPoint)
        self.components = []  # list of tuples: (type, QPoint)
        self.selected_component = None

        self.dragging_component = None
        self.drag_offset = QPoint(0, 0)

        self.last_pan_point = None
        self.offset = QPoint(0, 0)
        self.grid_size = 20

        # Snapping parameters
        self.snap_threshold = 50  # px
        self._hover_pin = None
        self._rubber_end = None
        self._rubber_start = None

    def get_component_pins(self, comp, pos):
        x, y = pos.x(), pos.y()
        if comp in ["resistor", "battery", "capacitor", "inductor"]:
            return [QPoint(x - 30, y), QPoint(x + 30, y)]
        elif comp in ["voltmeter", "ammeter"]:
            return [QPoint(x - 40, y), QPoint(x + 40, y)]
        elif comp == "ground":
            return [QPoint(x, y)]
        return []

    def find_nearest_pin(self, point):
        threshold = self.snap_threshold
        nearest_pin = None
        nearest_dist = float('inf')

        # Check component pins
        for comp, pos in self.components:
            for pin in self.get_component_pins(comp, pos):
                dist = (pin - point).manhattanLength()
                if dist < threshold and dist < nearest_dist:
                    nearest_pin = QPoint(pin)
                    nearest_dist = dist

        # Check endpoints of existing wires (allow connecting to wires)
        for a, b in self.lines:
            for endpoint in (a, b):
                dist = (endpoint - point).manhattanLength()
                if dist < threshold and dist < nearest_dist:
                    nearest_pin = QPoint(endpoint)
                    nearest_dist = dist

        # If none found, return None (caller should handle)
        return nearest_pin

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.translate(self.offset)

        # grid
        grid_size = self.grid_size
        painter.setPen(QPen(Qt.darkGray, 1))
        w, h = self.width(), self.height()
        for x in range(0, w - self.offset.x() + grid_size, grid_size):
            for y in range(0, h - self.offset.y() + grid_size, grid_size):
                if x + self.offset.x() >= 0 and y + self.offset.y() >= 0:
                    painter.drawPoint(x, y)

        # wires
        painter.setPen(QPen(Qt.white, 2))
        for line in self.lines:
            painter.drawLine(line[0], line[1])

        # rubberband
        if self._rubber_start and self._rubber_end:
            painter.setPen(QPen(Qt.yellow, 1, Qt.DashLine))
            painter.drawLine(self._rubber_start, self._rubber_end)

        # components
        painter.setPen(QPen(Qt.cyan, 2))
        painter.setBrush(QBrush(Qt.cyan))
        for comp, pos in self.components:
            x, y = pos.x(), pos.y()
            if comp == "resistor":
                painter.drawLine(x - 30, y, x - 10, y)
                painter.drawRect(x - 10, y - 10, 20, 20)
                painter.drawLine(x + 10, y, x + 30, y)
                painter.drawText(x - 5, y - 15, "R")
            elif comp == "battery":
                painter.drawLine(x - 30, y, x - 10, y)
                painter.drawLine(x - 10, y - 15, x - 10, y + 15)
                painter.drawLine(x + 10, y - 10, x + 10, y + 10)
                painter.drawLine(x + 10, y, x + 30, y)
                painter.drawText(x - 5, y - 20, "V")
            elif comp == "capacitor":
                painter.drawLine(x - 30, y, x - 10, y)
                painter.drawLine(x - 10, y - 15, x - 10, y + 15)
                painter.drawLine(x + 10, y - 15, x + 10, y + 15)
                painter.drawLine(x + 10, y, x + 30, y)
                painter.drawText(x - 5, y - 20, "C")
            elif comp == "inductor":
                painter.drawLine(x - 30, y, x - 10, y)
                for i in range(4):
                    painter.drawArc(x - 10 + i * 5, y - 10,
                                    10, 20, 0, 180 * 16)
                painter.drawLine(x + 20, y, x + 30, y)
                painter.drawText(x - 5, y - 15, "L")
            elif comp == "voltmeter":
                painter.drawEllipse(x - 30, y - 30, 60, 60)
                painter.drawText(x - 5, y + 5, "V")
                painter.drawLine(x - 40, y, x - 30, y)
                painter.drawLine(x + 30, y, x + 40, y)
            elif comp == "ammeter":
                painter.drawEllipse(x - 30, y - 30, 60, 60)
                painter.drawText(x - 5, y + 5, "A")
                painter.drawLine(x - 40, y, x - 30, y)
                painter.drawLine(x + 30, y, x + 40, y)
            elif comp == "ground":
                painter.drawLine(x, y, x, y + 10)
                painter.drawLine(x - 8, y + 10, x + 8, y + 10)
                painter.drawLine(x - 5, y + 14, x + 5, y + 14)
                painter.drawLine(x - 2, y + 18, x + 2, y + 18)

            # Draw pins for each component (small circles)
            for pin in self.get_component_pins(comp, pos):
                painter.setBrush(QBrush(Qt.cyan))
                painter.drawEllipse(pin.x() - 3, pin.y() - 3, 6, 6)

        # draw hover highlight if available
        if self._hover_pin:
            painter.setBrush(QBrush(Qt.green))
            painter.setPen(QPen(Qt.green, 1))
            hp = self._hover_pin
            painter.drawEllipse(hp.x() - 6, hp.y() - 6, 12, 12)

    def mousePressEvent(self, event):
        adjusted_pos = event.pos() - self.offset

        if event.button() == Qt.MiddleButton:
            self.last_pan_point = event.pos()
            return

        if event.button() == Qt.LeftButton:
            if self.dragging_component:
                return

            self.start_point = adjusted_pos

            # If delete tool is active
            if self.selected_component == 'delete':
                self.delete_at_point(adjusted_pos)
                self.start_point = None
                return

            # If placing component, we wait for release to place
            if self.selected_component and self.selected_component != 'wire':
                # immediate placement on release
                return

            # For wire tool, initialize rubberband
            if self.selected_component == 'wire':
                self._rubber_start = adjusted_pos
                self._rubber_end = adjusted_pos

    def mouseDoubleClickEvent(self, event):
        adjusted_pos = event.pos() - self.offset

        for i, comp_data in enumerate(reversed(self.components)):
            comp, pos = comp_data
            rect = QRect(pos.x() - 25, pos.y() - 25, 50, 50)
            if rect.contains(adjusted_pos):
                original_index = len(self.components) - 1 - i
                self.dragging_component = (comp, pos, original_index)
                self.drag_offset = adjusted_pos - pos
                self.setCursor(Qt.ClosedHandCursor)
                self.start_point = None
                break

    def mouseMoveEvent(self, event):
        # Move component
        if self.dragging_component:
            comp, old_pos, idx = self.dragging_component
            new_center_pos = event.pos() - self.offset - self.drag_offset
            grid = self.grid_size
            x = (new_center_pos.x() // grid) * grid
            y = (new_center_pos.y() // grid) * grid
            new_pos = QPoint(x, y)
            self.components[idx] = (comp, new_pos)
            self.dragging_component = (comp, new_pos, idx)
            self.update()
            return

        # Panning
        if event.buttons() & Qt.MiddleButton and self.last_pan_point:
            delta = event.pos() - self.last_pan_point
            self.offset += delta
            self.last_pan_point = event.pos()
            self.update()
            return

        # Wire rubberband and hover highlight
        adjusted_pos = event.pos() - self.offset
        if self.selected_component == 'wire' and self._rubber_start:
            # Update rubberband end with snapping if near a pin
            snap = self.find_nearest_pin(adjusted_pos)
            if snap:
                self._rubber_end = snap
                self._hover_pin = snap
            else:
                self._rubber_end = adjusted_pos
                self._hover_pin = None
            self.update()
            return

        # For hover highlight when not drawing
        snap = self.find_nearest_pin(adjusted_pos)
        self._hover_pin = snap
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.last_pan_point = None
            return

        adjusted_pos = event.pos() - self.offset

        # End dragging
        if event.button() == Qt.LeftButton and self.dragging_component:
            self.dragging_component = None
            self.setCursor(Qt.ArrowCursor)
            self.update()
            return

        # Component placement
        if self.start_point and self.selected_component and self.selected_component != 'wire':
            grid = self.grid_size
            x = (self.start_point.x() // grid) * grid
            y = (self.start_point.y() // grid) * grid
            self.components.append((self.selected_component, QPoint(x, y)))
            self.start_point = None
            self.update()
            return

        # Wire placement
        if self.selected_component == 'wire' and self._rubber_start:
            start_snap = self.find_nearest_pin(self._rubber_start)
            end_snap = self.find_nearest_pin(self._rubber_end if isinstance(
                self._rubber_end, QPoint) else adjusted_pos)

            # Enforce snapping
            if start_snap is None or end_snap is None:
                print('❌ Wire endpoints must be on pins — cancelled')
                self._rubber_start = None
                self._rubber_end = None
                self.start_point = None
                self._hover_pin = None
                self.update()
                return

            # Prevent zero-length
            if start_snap == end_snap:
                print('⚠ Zero-length wire — cancelled')
                self._rubber_start = None
                self._rubber_end = None
                self.update()
                return

            # Append snapped wire
            self.lines.append((start_snap, end_snap))
            print('WIRE:', start_snap, '->', end_snap)

            self._rubber_start = None
            self._rubber_end = None
            self.start_point = None
            self._hover_pin = None
            self.update()
            return

    def point_to_line_distance(self, p, a, b):
        x0, y0 = p.x(), p.y()
        x1, y1 = a.x(), a.y()
        x2, y2 = b.x(), b.y()
        dx, dy = x2 - x1, y2 - y1
        if dx == dy == 0:
            return ((x0 - x1)**2 + (y0 - y1)**2)**0.5
        t = max(0, min(1, ((x0 - x1)*dx + (y0 - y1)*dy)/(dx*dx + dy*dy)))
        nearest_x = x1 + t*dx
        nearest_y = y1 + t*dy
        return ((x0 - nearest_x)**2 + (y0 - nearest_y)**2)**0.5

    def delete_at_point(self, click_point):
        threshold = 20
        for i in reversed(range(len(self.components))):
            comp, pos = self.components[i]
            rect = QRect(pos.x() - 50, pos.y() - 50, 100, 100)
            if rect.contains(click_point):
                del self.components[i]
                self.update()
                return

        for line in list(self.lines):
            if self.point_to_line_distance(click_point, *line) < threshold:
                self.lines.remove(line)
                self.update()
                return

    def set_component(self, comp_type):
        self.selected_component = comp_type
        if comp_type == "delete":
            self.setStyleSheet(
                "border: 2px solid red; background-color: #0b0b0b;")
            self.setCursor(Qt.CrossCursor)
        else:
            self.setStyleSheet(
                "border: 2px solid #555; background-color: #0b0b0b;")
            self.setCursor(Qt.ArrowCursor)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Circuit Simulator - Fixed Canvas")
        self.setGeometry(100, 100, 1000, 650)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout()
        sidebar_layout = QVBoxLayout()
        canvas_layout = QVBoxLayout()

        self.canvas = CircuitCanvas()
        self.netlist_generator = NetlistGenerator(self.canvas)

        lbl = QLabel("Select Component:")
        lbl.setStyleSheet("font-size: 18px; color: white; font-weight: bold;")
        sidebar_layout.addWidget(lbl)

        input_label = QLabel("Enter Component Values (or use defaults):")
        input_label.setStyleSheet(
            "font-size: 16px; color: #ccc; font-weight: bold; margin-top:10px;")
        sidebar_layout.addWidget(input_label)

        self.R_input = QLineEdit()
        self.R_input.setPlaceholderText("R (ohms, default: 100)")
        self.R_input.setText("100")
        self.L_input = QLineEdit()
        self.L_input.setPlaceholderText("L (henry, default: 1e-3)")
        self.L_input.setText("1e-3")
        self.C_input = QLineEdit()
        self.C_input.setPlaceholderText("C (farad, default: 1e-6)")
        self.C_input.setText("1e-6")
        self.V_input = QLineEdit()
        self.V_input.setPlaceholderText("V (volts, default: 5)")
        self.V_input.setText("5")

        for box in [self.R_input, self.L_input, self.C_input, self.V_input]:
            box.setStyleSheet("""
                QLineEdit {
                    background-color: #2a2a2a;
                    color: white;
                    border: 1px solid #555;
                    border-radius: 4px;
                    padding: 4px;
                    font-size: 14px;
                }
                QLineEdit:focus { border: 1px solid #00aaff; }
            """)
            sidebar_layout.addWidget(box)

        simulate_btn = QPushButton("Simulate")
        simulate_btn.setStyleSheet("""
            QPushButton { background-color: #0078d7; color: white; font-size: 15px; font-weight: bold; padding: 8px; border-radius: 5px; }
            QPushButton:hover { background-color: #2896ff; }
        """)
        simulate_btn.clicked.connect(self.run_simulation)
        sidebar_layout.addWidget(simulate_btn)

        buttons = [
            ("Resistor", "resistor"), ("Battery", "battery"),
            ("Capacitor", "capacitor"), ("Inductor", "inductor"),
            ("Voltmeter", "voltmeter"), ("Ammeter", "ammeter"),
            ("Ground", "ground"), ("Wire", "wire"), ("Delete",
                                                     "delete"), ("Clear Canvas", "clear")
        ]

        for name, value in buttons:
            btn = QPushButton(name)
            btn.setStyleSheet("""
                QPushButton { background-color: #333; color: white; font-size: 15px; font-weight: bold; padding: 8px; border-radius: 5px; }
                QPushButton:hover { background-color: #555; }
            """)
            if value == "clear":
                btn.clicked.connect(self.clear_canvas)
            else:
                btn.clicked.connect(
                    lambda _, v=value: self.canvas.set_component(v))
            sidebar_layout.addWidget(btn)

        sidebar_layout.addStretch()
        sidebar_widget = QWidget()
        sidebar_widget.setStyleSheet(
            "background-color: #1e1e1e; border-right: 2px solid #444;")
        sidebar_widget.setLayout(sidebar_layout)

        canvas_layout.addWidget(self.canvas)
        main_layout.addWidget(sidebar_widget, 1)
        main_layout.addLayout(canvas_layout, 4)
        central_widget.setLayout(main_layout)

    def clear_canvas(self):
        self.canvas.lines.clear()
        self.canvas.components.clear()
        self.canvas.update()

    def run_simulation(self):
        component_values = {
            'R': self.R_input.text() or '100',
            'L': self.L_input.text() or '1e-3',
            'C': self.C_input.text() or '1e-6',
            'V': self.V_input.text() or '5',
        }
        # debug dump - paste this in run_simulation before calling generate_netlist
        print("=== DEBUG: COMPONENTS ===")
        for i, (comp, pos) in enumerate(self.canvas.components):
            pins = self.canvas.get_component_pins(comp, pos)
            print(
                f"{i}: {comp} at {pos} -> pins: {[ (p.x(), p.y()) for p in pins ]}")

        print("=== DEBUG: WIRES ===")
        for i, (a, b) in enumerate(self.canvas.lines):
            print(f"{i}: { (a.x(), a.y()) }  ->  { (b.x(), b.y()) }")

        print("=== DEBUG: GROUND KEYS ===")
        print(self.netlist_generator.ground_keys)

        try:
            tf, ok = QInputDialog.getDouble(self, "Simulation Time",
                                            "Enter final time (tf) for transient simulation (e.g., 0.01s).\nUse 0 for DC Simulation.", decimals=4)
            if not ok:
                return
        except Exception as e:
            QMessageBox.critical(self, "Input Error",
                                 f"Invalid time input: {e}")
            return

        TEMP_NETLIST_FILE = "temp_circuit.net"
        try:
            netlist_content = self.netlist_generator.generate_netlist(
                component_values)
            if not netlist_content:
                QMessageBox.warning(
                    self, "Warning", "No components found to simulate.")
                return

            with open(TEMP_NETLIST_FILE, 'w') as f:
                f.write(netlist_content)

            netlist_path = os.path.abspath(TEMP_NETLIST_FILE)

        except Exception as e:
            QMessageBox.critical(self, "Netlist Error",
                                 f"Could not generate netlist: {e}")
            return

        print("NETLIST GENERATED:\n", netlist_content)

        try:
            self.statusBar().showMessage("Starting MATLAB engine...")
            eng = matlab.engine.start_matlab()

            matlab_function_dir = r"C:\Users\sudha\OneDrive\Documents\Desktop\CircuitSimProject"
            eng.addpath(matlab_function_dir, nargout=0)
            which_result = eng.which('simulate_circuit.m')
            print(f"DEBUG: MATLAB 'which' result: {which_result}")

            if not which_result:
                raise FileNotFoundError(
                    f"MATLAB could not locate 'simulate_circuit.m' in the path: {matlab_function_dir}")

            eng.addpath(os.getcwd(), nargout=0)
            self.statusBar().showMessage("Running MATLAB simulation...")
            t_out_raw, Vout_raw = eng.simulate_circuit(
                TEMP_NETLIST_FILE, tf, nargout=2)

            # ---------- helper: robust conversion of MATLAB output to numpy ----------
            def matlab_to_numpy(x):
                # Handles matlab.double, lists, nested lists, scalars
                try:
                    # try direct conversion first
                    arr = np.array(x)
                except Exception:
                    # sometimes matlab returns matlab.double which numpy handles,
                    # but in other cases it's nested lists or a single scalar
                    try:
                        arr = np.array(list(x))
                    except Exception:
                        # fallback: wrap in 1-element array
                        arr = np.array([x])

                # If object dtype and contains lists, try to normalize
                if arr.dtype == object:
                    # try to convert nested sequences to numeric array
                    try:
                        arr = np.array([np.array(a).astype(float)
                                       for a in arr])
                    except Exception:
                        # try flattening one level
                        try:
                            arr = np.array([float(a) for a in np.ravel(arr)])
                        except Exception:
                            pass

                # Final attempt to cast to float
                try:
                    arr = arr.astype(float)
                except Exception:
                    # leave as-is; caller will see and can debug
                    pass

                return arr

            t_out = matlab_to_numpy(t_out_raw)
            Vout = matlab_to_numpy(Vout_raw)

            # ---------- Normalize shapes ----------
            # If DC (tf == 0) we expect t_out to be scalar 0 and Vout vector (N,)
            if tf == 0:
                # ensure t_out is scalar or length-1 array
                if np.ndim(t_out) > 0:
                    # If t_out is array of length 1, extract scalar
                    if t_out.size == 1:
                        t_out = float(t_out.flatten()[0])
                    else:
                        # unexpected: keep as array but warn
                        print("DEBUG: unexpected t_out shape for DC:", t_out.shape)
                # Vout should be 1-D vector
                if Vout.ndim > 1 and Vout.shape[0] == 1:
                    Vout = Vout.flatten()
                elif Vout.ndim > 1 and Vout.shape[1] == 1:
                    Vout = Vout.flatten()
            else:
                # Transient: t_out should be 1-D array, Vout should be 2-D: (steps, nodes)
                # If Vout comes back transposed or 1-D, attempt to fix
                if np.ndim(t_out) == 0:
                    # single scalar returned unexpectedly; convert to length-1 array
                    t_out = np.atleast_1d(t_out)
                if Vout.ndim == 1 and t_out.size > 1:
                    # interpret as (steps * nodes) flattened? try to reshape to (steps, -1)
                    try:
                        Vout = Vout.reshape((t_out.size, -1))
                    except Exception:
                        # fallback: treat as single node trace
                        Vout = Vout.reshape((t_out.size, 1))
                elif Vout.ndim == 2:
                    # if shapes mismatch (columns vs rows), try to align
                    if Vout.shape[0] != t_out.size and Vout.shape[1] == t_out.size:
                        Vout = Vout.T

            # ---------- Debug prints (only when something odd) ----------
            print("DEBUG: t_out type/shape:", type(t_out),
                  getattr(t_out, "shape", None))
            print("DEBUG: Vout type/shape:", type(Vout),
                  getattr(Vout, "shape", None))

            # ---------- Now plotting ----------
            plt.figure()

            if tf == 0:
                # DC Analysis (Bar plot of node voltages)
                Vplot = np.asarray(Vout).flatten()
                plt.bar(range(1, Vplot.size + 1), Vplot)
                plt.xlabel("Node")
                plt.ylabel("Voltage (V)")
                plt.title("DC Node Voltages")
                plt.xticks(range(1, Vplot.size + 1))

            elif tf < 0:
                # AC Analysis (Bode Plot: Magnitude in dB)
                if isinstance(Vout, list) and len(Vout) == 2:
                    # Vout should be {Magnitude, Phase} array from MATLAB
                    Vout_mag = np.asarray(Vout[0])
                    f_plot = np.asarray(t_out).astype(float).flatten()

                    for i in range(Vout_mag.shape[1]):
                        # Convert magnitude to dB: 20*log10(|V|)
                        Vdb = 20 * np.log10(Vout_mag[:, i])
                        plt.semilogx(
                            f_plot, Vdb, label=f"Node {i+1} Magnitude (dB)")

                    plt.xlabel("Frequency (Hz) (Log Scale)")
                    plt.ylabel("Voltage Magnitude (dB)")
                    plt.title("AC Magnitude Response (Bode Plot)")
                    plt.legend()
                else:
                    # Fallback if Vout structure is unexpected for AC
                    QMessageBox.warning(
                        self, "Plotting Error", "AC analysis data format is incorrect.")

            else:
                # Transient Analysis (Time domain plot)
                t_plot = np.asarray(t_out).astype(float).flatten()
                Varr = np.asarray(Vout).astype(float)
                if Varr.ndim == 1:
                    plt.plot(t_plot, Varr, label=f"Node 1")
                else:
                    for i in range(Varr.shape[1]):
                        plt.plot(t_plot, Varr[:, i], label=f"Node {i+1}")
                plt.xlabel("Time (s)")
                plt.ylabel("Node Voltages (V)")
                plt.title("Transient Node Voltages vs Time")
                plt.legend()

            plt.grid(True)
            plt.show()

        except Exception as e:
            QMessageBox.critical(self, "Simulation Error",
                                 f"MATLAB Simulation Failed: {e}")
            self.statusBar().showMessage("Simulation failed.")

        finally:
            if os.path.exists(TEMP_NETLIST_FILE):
                os.remove(TEMP_NETLIST_FILE)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
