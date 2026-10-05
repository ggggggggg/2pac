from pathlib import Path

DESKTOP_DIR = Path.home() / "Desktop" / "custom_scripts"
DESKTOP_DIR.mkdir(parents=True, exist_ok=True)

SCRIPTS = {
    "he3_adr_cycle.txt": """# He3 ADR Cycle Custom Script
# 1. Close heatswitches pot & adr, open charcoal, wait until pot < 3.2K
close heatswitch pot
wait 1 s
close heatswitch adr
wait 1 s
open heatswitch charcoal
wait 1 s

while True:
    mr = most_recent_measurements()
    if mr.get("cryocon_chC_temperature", 100) < 3.2:
        break
    world.wait(1)

# 2. Start heating charcoal
world.station.cryocon.loop1_source("A")
world.wait(1)
world.station.cryocon.loop1_setpoint(65)
world.wait(1)
world.station.cryocon.loop2_source("B")
world.wait(1)
world.station.cryocon.loop2_setpoint(55)
world.wait(1)
world.station.cryocon.control_enabled(True)
world.wait(1)

# 3. Ramp up ADR
set relay RAMP
world.wait(1)
ramp_controller = world.station.ls370.heater
ramp_controller.mode('open_loop')
world.wait(1)
ramp_controller.range("100uA")
world.wait(1)

target_hout = 58.1
target_time_s = 1800
target_step_duration_s = 1
target_N_steps = int(target_time_s / target_step_duration_s)
step_size = target_hout / target_N_steps
houts_up = np.arange(target_N_steps) * step_size
for hout in houts_up:
    ramp_controller.out(hout)
    world.wait(target_step_duration_s)
    print("CLOSE THE GREEN HE3 VALVE")

# 4. Wait for He3 to condense
world.wait(12600)

# 5. Cool charcoal
open heatswitch pot
world.wait(1)
world.station.cryocon.control_enabled(False)
world.wait(120)
close heatswitch charcoal
world.wait(1)
world.wait(3660)

world.station.cryocon.loop1_setpoint(65)
world.wait(1)
world.station.cryocon.loop2_source("B")
world.wait(1)
world.station.cryocon.loop2_setpoint(1)
world.wait(1)
world.station.cryocon.control_enabled(True)
world.wait(1800)
world.station.cryocon.control_enabled(False)
world.wait(7320)

# 6. Ramp down ADR
open heatswitch adr
world.wait(1)
houts_down = houts_up[::-1]
for hout in houts_down:
    ramp_controller.out(hout)
    world.wait(target_step_duration_s)

world.wait(1200)
set relay CONTROL
world.wait(30)
ramp_controller.mode('closed')
world.wait(1)
ramp_controller.setpoint(0.05)
world.wait(1)
ramp_controller.range("100uA")

return wait_forever
""",

    "ready_for_cooldown.txt": """# Ready For Cooldown Script
close heatswitch pot
close heatswitch adr
close heatswitch charcoal
wait 3 s

world.station.cryocon.loop1_source("A")
world.station.cryocon.loop1_setpoint(45)
world.station.cryocon.loop2_source("B")
world.station.cryocon.loop2_setpoint(55)
world.station.cryocon.control_enabled(False)
print("OPEN THE GREEN HE3 VALVE")
wait 1000000 s
""",

    "warmup_300K.txt": """# Warmup 300K Script
close heatswitch pot
close heatswitch adr
close heatswitch charcoal
wait 3 s

world.station.cryocon.loop1_source("A")
world.station.cryocon.loop1_setpoint(295)
world.station.cryocon.loop2_source("B")
world.station.cryocon.loop2_setpoint(295)
world.station.cryocon.control_enabled(True)
wait 1e15 s
""",

    "open_charcoal_heatswitch.txt": """# Open Charcoal Heat Switch
open heatswitch charcoal
return wait_forever
""",

    "open_pot_heatswitch.txt": """# Open Pot Heat Switch
open heatswitch pot
return wait_forever
""",

    "open_adr_heatswitch.txt": """# Open ADR Heat Switch
open heatswitch adr
return wait_forever
""",

    "set_relay_to_ramp.txt": """# Set Relay to RAMP
set relay RAMP
return wait_forever
""",

    "switch_to_wait_forever_test.txt": """# Switch to Wait Forever Test
return wait_forever
""",

    "wait_forever.txt": """# Idle Wait Forever State
while True:
    world.wait(1)
""",

    "wait_forever2.txt": """# Extended Idle State
world.wait(1e18)
"""
}

for fname, content in SCRIPTS.items():
    file_path = DESKTOP_DIR / fname
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")
    print(f"Exported: {file_path}")
