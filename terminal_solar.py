import sys
import time
from pymodbus.client import ModbusTcpClient
from pymodbus.framer import FramerType

# ==============================================================================
# 🌞 EPEVER TRACER 3210 MPPT TERMINAL MONITOR (FIXED PYMODBUS CODES)
# ==============================================================================
DONGLE_IP = "192.168.1.249"  # <-- Replace with your exact Extender Portal IP
PORT = 9999
DEVICE_ID = 1

def fetch_mppt_data():
    client = ModbusTcpClient(DONGLE_IP, port=PORT, framer=FramerType.RTU)
    if not client.connect():
        return {"status": "Disconnected ❌", "v_pv": 0.0, "a_pv": 0.0, "w_pv": 0.0, "v_bat": 0.0, "a_bat": 0.0, "w_bat": 0.0, "device_t": 0.0, "battery_t": 0.0, "total_kwh": 0.0, "state": "OFFLINE"}
    
    try:
        # WAKE UP INJECTION: Keeps the dongle awake after a cold reboot
        client.socket.send(bytes.fromhex("20020000"))
        time.sleep(0.2)
        
        # Read Live telemetry (18 registers starting at 0x3100 / 12544)
        rt_result = client.read_input_registers(address=12544, count=18, device_id=DEVICE_ID)
        # Read History metrics (2 registers starting at 0x3312 / 13074)
        stats_result = client.read_input_registers(address=13074, count=2, device_id=DEVICE_ID)
        
        if rt_result.isError() or stats_result.isError():
            raise Exception("Modbus payload dropped by device")
            
        rt = rt_result.registers
        stats = stats_result.registers
        
        # 1. Parse Solar Array Input Data (Using precise register array indexing)
        pv_v = rt[0] / 100.0  # Register 0x3100
        pv_a = rt[1] / 100.0  # Register 0x3101
        pv_w = pv_v * pv_a
        
        # 2. Parse Battery Bus Telemetry (From the controller output side)
        batt_v = rt[4] / 100.0  # Register 0x3104
        batt_a = rt[5] / 100.0  # Register 0x3105
        batt_w = batt_v * batt_a
        
        # 3. Parse Device and Battery Probes (Registers 0x3110 and 0x3111 -> indices 16 & 17)
        battery_temp = rt[16] / 100.0
        device_temp = rt[17] / 100.0
        
        # 4. Parse Cumulative Energy Yield (32-bit: low 16-bits, then high 16-bits)
        total_kwh = (stats[0] | (stats[1] << 16)) / 100.0

        # 5. Extract Charging Status (Register 0x310A -> index 10)
        status_raw = rt[10]
        if status_raw == 0x01: mppt_state = "BULK CHARGE 🚀"
        elif status_raw == 0x02: mppt_state = "BOOST/ABSORPTION ⚡"
        elif status_raw == 0x03: mppt_state = "FLOAT MAINTENANCE 💤"
        else: mppt_state = "PV HARVEST ACTIVE ☀️" if pv_w > 5.0 else "NIGHT / IDLE 🌙"

        return {
            "status": "Online ✅", "v_pv": pv_v, "a_pv": pv_a, "w_pv": pv_w,
            "v_bat": batt_v, "a_bat": batt_a, "w_bat": batt_w,
            "battery_t": battery_temp, "device_t": device_temp,
            "total_kwh": total_kwh, "state": mppt_state
        }
        
    except Exception as e:
        return {"status": f"Error ❌ ({str(e)})", "v_pv": 0.0, "a_pv": 0.0, "w_pv": 0.0, "v_bat": 0.0, "a_bat": 0.0, "w_bat": 0.0, "device_t": 0.0, "battery_t": 0.0, "total_kwh": 0.0, "state": "OFFLINE"}
    finally:
        client.close()

def main_loop():
    try:
        while True:
            data = fetch_mppt_data()
            
            # ANSI escape codes to clear the terminal screen cleanly every loop
            print("\033[H\033[J", end="") 
            print("=====================================================")
            print("        EPEVER TRACER 3210 MPPT HARDWARE PANEL       ")
            print("=====================================================")
            print(f" COM STATUS        :  {data['status']}")
            print(f" CHARGER STATE     :  {data['state']}")
            print("-----------------------------------------------------")
            print(f" SOLAR ARRAY INPUT (PV)")
            print(f"   Voltage         :  {data['v_pv']:.2f} V")
            print(f"   Amperage        :  {data['a_pv']:.2f} A")
            print(f"   Generation      :  {data['w_pv']:.1f} W")
            print("-----------------------------------------------------")
            print(f" MPPT BATTERY BUS OUTPUT TERMINALS")
            print(f"   Charging Voltage:  {data['v_bat']:.2f} V")
            print(f"   Generating Amps :  {data['a_bat']:.2f} A")
            print(f"   Net Bus Power   :  {data['w_bat']:.1f} W")
            print("-----------------------------------------------------")
            print(f" SYSTEM TEMPERATURE REGISTERS")
            print(f"   Batter Probe    :  {data['battery_t']:.1f} °C")
            print(f"   Controller Temp :  {data['device_t']:.1f} °C")
            print("-----------------------------------------------------")
            print(f" CUMULATIVE ENERGY YIELD METRICS")
            print(f"   Total Generation:  {data['total_kwh']:.2f} kWh")
            print("=====================================================")
            print(" [Press Ctrl+C to stop monitor safely]")
            
            time.sleep(3)
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")

if __name__ == "__main__":
    main_loop()
