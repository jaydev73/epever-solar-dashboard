import os
import time
from flask import Flask, render_template_string, jsonify, redirect, url_for
from pymodbus.client import ModbusTcpClient
from pymodbus.framer import FramerType
from dotenv import load_dotenv

# Load parameters securely out of your hidden .env file
load_dotenv()
import logging  # <-- Add this import at the top of your script

app = Flask(__name__)

# 🤫 SILENCE THE FLASK ENGINE ACCES LOGS
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)  # Only print lines if a serious system error crashes

# CONFIGURATION (Pulled securely from environment variables)
DONGLE_IP = os.getenv("EPEVER_DONGLE_IP")
PORT = int(os.getenv("EPEVER_PORT", 9999))
DEVICE_ID = int(os.getenv("EPEVER_DEVICE_ID", 1))

def fetch_mppt_data():
    client = ModbusTcpClient(DONGLE_IP, port=PORT, framer=FramerType.RTU)
    if not client.connect():
        return None
    try:
        # Wake up frame for the EPEVER network dongle 
        client.socket.send(bytes.fromhex("20020000"))
        time.sleep(0.2)
        
        # Read Live telemetry (18 registers starting at 0x3100)
        rt_result = client.read_input_registers(address=12544, count=18, device_id=DEVICE_ID)
        
        # Read Charging Equipment Status Register (1 register at 0x3201 / 12801)
        status_result = client.read_input_registers(address=12801, count=1, device_id=DEVICE_ID)
        
        # Read History metrics (2 registers starting at 0x3312 / 13074)
        stats_result = client.read_input_registers(address=13074, count=2, device_id=DEVICE_ID)
        
        if rt_result.isError() or status_result.isError() or stats_result.isError():
            return None
            
        rt = rt_result.registers
        status_reg = status_result.registers
        stats = stats_result.registers
        
        # 🛡️ DIAGNOSTIC SAFETY BOUNDS CHECK
        # This prevents the 'list index out of range' crash if an array returns short
        if len(rt) < 18 or len(status_reg) < 1 or len(stats) < 2:
            print(f"⚠️ Warning: Short packet received. rt={len(rt)}, status={len(status_reg)}, stats={len(stats)}")
            return None

        pv_v = rt[0] / 100.0  
        pv_a = rt[1] / 100.0  
        pv_w = pv_v * pv_a
        
        batt_v = rt[4] / 100.0  
        batt_a = rt[5] / 100.0  
        batt_w = batt_v * batt_a
        
        load_v = rt[12] / 100.0
        load_a = rt[13] / 100.0
        load_w = load_v * load_a
        
        device_temp = rt[16] / 100.0
        battery_temp = rt[17] / 100.0
        total_kwh = (stats[0] | (stats[1] << 16)) / 100.0

        # Extract bits D3-D2 out of register 0x3201
        charge_bits = (status_reg[0] >> 2) & 0x03
        
        if charge_bits == 0x01:
            mppt_state = "FLOAT MAINTENANCE 💤"
        elif charge_bits == 0x02:
            mppt_state = "BOOST / ABSORPTION ⚡"
        elif charge_bits == 0x03:
            mppt_state = "EQUALIZATION CHARGE 🔥"
        else:
            mppt_state = "BULK CHARGE 🚀" if pv_w > 8.0 else "IDLE / NIGHT 🌙"

        return {
            "state": mppt_state, "v_pv": pv_v, "w_pv": pv_w,
            "v_bat": batt_v, "w_bat": batt_w,
            "device_t": device_temp, "battery_t": battery_temp,
            "total_kwh": total_kwh, "v_load": load_v, "a_load": load_a, "w_load": load_w
        }
    except Exception as e:
        print(f"Modbus Telemetry Error: {e}")
        return None
    finally:
        client.close()

def toggle_mppt_load(state_to_set):
    """Writes to Modbus Coil 0x0002 to switch the 12V terminal on or off."""
    client = ModbusTcpClient(DONGLE_IP, port=PORT, framer=FramerType.RTU)
    if not client.connect():
        return False
    try:
        client.socket.send(bytes.fromhex("20020000"))
        time.sleep(0.2)
        result = client.write_coil(address=2, value=state_to_set, device_id=DEVICE_ID)
        return not result.isError()
    except Exception as e:
        print(f"Coil mutation transmission failure: {e}")
        return False
    finally:
        client.close()

# HTML & CSS Interface with interactive control options
WEB_UI = """
<!DOCTYPE html>
<html>
<head>
    <title>Solar Station Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: Arial, sans-serif; background: #121214; color: #fff; text-align: center; padding: 20px; }
        .grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 15px; max-width: 900px; margin: 20px auto; }
        .card { background: #202024; padding: 20px; border-radius: 10px; width: 180px; border: 1px solid #29292e; }
        .label { font-size: 0.8rem; color: #a8a8b3; text-transform: uppercase; }
        .value { font-size: 1.6rem; font-weight: bold; margin-top: 5px; color: #04d361; }
        .control-panel { background: #202024; max-width: 400px; margin: 30px auto; padding: 25px; border-radius: 12px; border: 1px solid #29292e; }
        .btn { display: inline-block; padding: 12px 30px; font-size: 1rem; font-weight: bold; text-decoration: none; border-radius: 6px; margin: 10px; cursor: pointer; color: white; border: none; }
        .btn-on { background: #04d361; }
        .btn-on:hover { background: #029944; }
        .btn-off { background: #f75a68; }
        .btn-off:hover { background: #c73e4b; }
        .status-tag { font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; }
    </style>
</head>
<body>
    <h1>Solar Controller Interactive Panel</h1>
    <h2 id="mppt_state" style="color: #ffeb3b;">CHARGER STATE: LOADING...</h2>

    <div class="control-panel">
        <h3>12V DC Output Load Control</h3>
        <div class="status-tag" id="load_status">Load State: Loading...</div>
        <form action="/load/on" method="POST" style="display: inline;"><button class="btn btn-on">TURN ON</button></form>
        <form action="/load/off" method="POST" style="display: inline;"><button class="btn btn-off">TURN OFF</button></form>
    </div>

    <div class="grid">
        <div class="card"><div class="label">PV Voltage</div><div class="value" id="pv_v">-- V</div></div>
        <div class="card"><div class="label">PV Power</div><div class="value" id="pv_w">-- W</div></div>
        <div class="card"><div class="label">Battery Voltage</div><div class="value" id="bat_v">-- V</div></div>
        <div class="card"><div class="label">Load Power</div><div class="value" id="load_w">-- W</div></div>
        <div class="card"><div class="label">Controller Temp</div><div class="value" id="c_temp">-- °C</div></div>
        <div class="card"><div class="label">Total Generated</div><div class="value" id="total_gen">-- kWh</div></div>
    </div>

    <script>
        async function updateTelemetry() {
            try {
                const response = await fetch('/api/data');
                const data = await response.json();
                
                document.getElementById('mppt_state').innerText = "CHARGER STATE: " + data.state;
                document.getElementById('pv_v').innerText = data.v_pv.toFixed(2) + " V";
                document.getElementById('pv_w').innerText = data.w_pv.toFixed(1) + " W";
                document.getElementById('bat_v').innerText = data.v_bat.toFixed(2) + " V";
                document.getElementById('load_w').innerText = data.w_load.toFixed(1) + " W";
                document.getElementById('c_temp').innerText = data.device_t.toFixed(1) + " °C";
                document.getElementById('total_gen').innerText = data.total_kwh.toFixed(2) + " kWh";
                
                if(data.v_load > 2.0) {
                    document.getElementById('load_status').innerHTML = 'Load State: <span style="color:#04d361;">ON 🟢</span> (' + data.a_load.toFixed(2) + ' A)';
                } else {
                    document.getElementById('load_status').innerHTML = 'Load State: <span style="color:#f75a68;">OFF 🔴</span>';
                }
            } catch(e) { console.error("Telemetry link lost"); }
        }
        setInterval(updateTelemetry, 2500);
        updateTelemetry();
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(WEB_UI)

@app.route('/api/data')
def api_data():
    metrics = fetch_mppt_data()
    return jsonify(metrics) if metrics else (jsonify({"error": "Offline"}), 500)

@app.route('/load/on', methods=['POST'])
def load_on():
    toggle_mppt_load(True)
    return redirect(url_for('home'))

@app.route('/load/off', methods=['POST'])
def load_off():
    toggle_mppt_load(False)
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
