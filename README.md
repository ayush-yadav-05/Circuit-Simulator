# Circuit Simulator

A visual circuit simulator with a PyQt5 GUI and a MATLAB-based Modified Nodal Analysis (MNA) solver. Draw circuits on a canvas, then run DC, transient, or AC analysis and view the results.

## Features

- **Visual canvas**: Place resistors, batteries, capacitors, inductors, voltmeters, ammeters, and ground symbols; connect them with wires (snap-to-pin).
- **Netlist generation**: Automatically builds a SPICE-style netlist from the drawn circuit.
- **Simulation modes**:
  - **DC** (tf = 0): Steady-state node voltages.
  - **Transient** (tf > 0): Time-domain analysis using Backward Euler.
  - **AC** (tf < 0): Frequency sweep with Bode (magnitude) plot.
- **Plotting**: Results shown via matplotlib (bar chart for DC, time plot for transient, Bode for AC).

## Requirements

- **Python 3** with:
  - PyQt5
  - matplotlib
  - numpy
  - MATLAB Engine for Python (`matlab.engine`)
- **MATLAB** (installed and on PATH) for running the MNA solver.

## Installation

1. Install Python dependencies:
   ```bash
   pip install PyQt5 matplotlib numpy
   pip install matlabengine
   ```
   (Install MATLAB Engine per [MathWorks instructions](https://www.mathworks.com/help/matlab/matlab_external/install-the-matlab-engine-for-python.html).)

2. Ensure `simulate_circuit.m` is on the MATLAB path. In `project2.py`, the script adds a directory where it looks for the MATLAB function—update `matlab_function_dir` if your `.m` file lives elsewhere.

## Usage

Run the GUI:

```bash
python project2.py
```

1. Select a component from the sidebar and click on the canvas to place it (or choose **Wire** to draw connections).
2. Enter component values (R, L, C, V) or use the defaults.
3. Click **Simulate**, enter the final time **tf** when prompted:
   - **tf = 0** → DC analysis  
   - **tf > 0** (e.g. `0.01`) → Transient analysis  
   - **tf < 0** (e.g. `-1`) → AC / Bode analysis  
4. View the result in the matplotlib window.

**Tips**: Double-click a component to drag it. Use the middle mouse button to pan the canvas. Use **Delete** to remove components or wires, and **Clear Canvas** to start over.

## Project Structure

| File              | Description                                      |
|-------------------|--------------------------------------------------|
| `project2.py`     | PyQt5 GUI, canvas, netlist generator, MATLAB call, plotting |
| `simulate_circuit.m` | MATLAB MNA solver (DC / transient / AC)       |

## License

MIT — see [LICENSE](LICENSE).
