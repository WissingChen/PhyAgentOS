# PAOS Simulation Environment Guide

> **English** | [中文](README_paos_env_zh.md)

This guide covers how to set up and run PhyAgentOS with simulation environments, including the built-in lightweight simulation and NVIDIA Isaac Sim 5.1.

---

## Table of Contents

- [Built-in Simulation (Recommended for First-Time)](#built-in-simulation-recommended-for-first-time)
- [Isaac Sim 5.1 Simulation](#isaac-sim-51-simulation)
- [G1 Humanoid Simulation](#g1-humanoid-simulation)
- [Multi-Robot Simulation](#multi-robot-simulation)
- [Troubleshooting](#troubleshooting)

---

## Built-in Simulation (Recommended for First-Time)

The built-in simulation requires no additional installation beyond `watchdog`:

```bash
pip install watchdog
```

### Quick Start

```bash
# Terminal 1: Start simulation watchdog
python hal/hal_watchdog.py --driver simulation

# Terminal 2: Start agent
paos agent -m "look around the room"
```

### Supported Actions

- `move_to`, `pick_up`, `put_down`, `push`, `grasp`, `stop`

### Notes

- Keep only one watchdog process running.
- If the simulator is laggy, adjust `--interval` (default 0.05s = 20Hz).
- If you modify driver or skill files, restart the watchdog.

---

## Isaac Sim 5.1 Simulation

For high-fidelity physics simulation with visual rendering.

### Prerequisites

1. Install Isaac Sim 5.1.0:
   - Download: [https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/download.html](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/download.html)
   - Quick install: [https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/quick-install.html](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/quick-install.html)

2. Prepare Python environment:

```bash
conda activate paos
```

3. Install dependencies:

```bash
cd /path/to/PhyAgentOS
conda env create -f environment.yml
pip install -e .
```

### Start HAL Watchdog (GUI Mode)

```bash
cd /path/to/PhyAgentOS
conda activate paos
python hal/hal_watchdog.py \
  --gui \
  --interval 0.05 \
  --driver pipergo2_manipulation \
  --driver-config examples/pipergo2_manipulation_driver.json
```

## 4b) Start HAL watchdog (VNC mode, for containers without local X)

```bash
cd /home/zyserver/work/PhyAgentOS
conda activate paos
python hal/hal_watchdog.py --vnc --interval 0.05 --driver pipergo2_manipulation --driver-config examples/pipergo2_manipulation_driver.json
```

Then open a browser at `http://<host>:31315/vnc.html` to see the Isaac Sim window.

Notes:
- `--vnc` auto-bootstraps Isaac Sim env **inside the Python process** using the
  `isaac_env` block of the driver-config JSON: sets `DISPLAY` (defaults to
  `:99`), injects `ISAAC_PATH` / `CARB_APP_PATH` / `EXP_PATH` /
  `INTERNUTOPIA_ASSETS_PATH`, sources `setup_python_env.sh`, and prepends
  `extra_pythonpath` to both `PYTHONPATH` and `sys.path`. Users no longer need
  to wrap the command in a shell script that `source`s those vars.
- `--gui` and `--vnc` are mutually exclusive. Without either flag the
  watchdog runs headless.
- On first start in `--vnc` mode the watchdog **re-execs itself once**
  (`[isaac-bootstrap] LD_LIBRARY_PATH changed; re-exec ...` →
  `[isaac-bootstrap] post-reexec ready ...`). This is required because
  glibc's dynamic loader caches `LD_LIBRARY_PATH` at process start, so
  `libcarb.so` / `isaacsim` imports only succeed after the process is
  restarted with the environment sourced from `setup_python_env.sh`.
- Customize the Isaac Sim / InternUtopia paths in
  `examples/pipergo2_manipulation_driver.json` under the `isaac_env` key.

## 5) Send PAOS agent commands

Open another terminal:

```bash
cd /path/to/PhyAgentOS
conda activate paos
paos agent -m "open simulation"
paos agent -m "go to desk"
paos agent -m "what is on the table"
paos agent -m "pick up the red cube and return to the starting position"
```

The table question is answered immediately from the current `ENVIRONMENT.md` scene graph / manipulation runtime state. In fleet mode, include the target `robot_id` in the tool call context.

---

## Multi-Robot Simulation

To run multiple robots in the same Isaac Sim scene:

```bash
# Example: Piper + Go2 + Franka in one scene
python hal/hal_watchdog.py \
  --driver multi_robot_simulation \
  --driver-config examples/pipergo2_franka_same_scene_internutopia_config.json
```

For fleet mode with separate workspaces per robot, see [Fleet Mode Guide](user_manual/03_FLEET_MODE.md).

---

## Troubleshooting

### Isaac Sim not found

- Confirm Isaac Sim 5.1 is installed and the `isaacsim` package is in your Python path
- Try: `python -c "import isaacsim; print(isaacsim.__version__)"`

### GUI mode fails

- Check GPU driver and CUDA compatibility
- Try without `--gui` for headless mode
- Check Isaac Sim logs for rendering errors

### Actions not executing in simulation

- Confirm only one watchdog is running
- Check `--interval` is set appropriately (0.05 for 20Hz)
- Verify the driver config JSON points to a valid scene file (`.usd`)

---

## Next Steps

- [User Manual: Basic Usage](user_manual/02_BASIC_USAGE.md) for general commands
- [Embodiments Guide](user_manual/04_EMBODIMENTS.md) for connecting real robots
- [Plugin Development Guide](user_development_guide/PLUGIN_DEVELOPMENT_GUIDE.md) for adding new simulation backends
