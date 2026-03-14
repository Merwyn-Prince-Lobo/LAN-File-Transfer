"""
LAN File Transfer App
by Merwyn (or whoever is reading this lol)

Now with ROOMS support! Each group uses their own room name + passkey.
Only people with the same room passkey can see each other. Different groups
are completely invisible to each other even on the same network. pretty cool

Requirements:
    pip install flask pycryptodome requests

Usage:
    python3 app.py               # default port 5000
    python3 app.py --port 5001   # for local testing with 2 instances
    ts is for debuggin purposes, you can open multiple tabs to the same room with different names
"""

import os
import json
import uuid
import socket
import hashlib
import argparse
import threading
import time

from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, session
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes

# ---- Parse command line args ----
parser = argparse.ArgumentParser(description="LAN File Transfer")
parser.add_argument("--port", type=int, default=5000, help="Port to run on (default: 5000)")
parser.add_argument("--name", type=str, default=None, help="Display name (default: hostname)")
args = parser.parse_args()

# ---- Config ----
DISCOVERY_PORT = 55555
FLASK_PORT = args.port
SECRET_KEY = "changethisplease"
UPLOAD_FOLDER = f"uploads_{FLASK_PORT}"  # separate per instance for local testing

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---- Global state ----
# { "ip:port": { ip, name, port, last_seen } }
discovered_peers = {}
peers_lock = threading.Lock()

room_name = None      # display name e.g. "merwyns-room"
room_passkey = None   # raw passkey
room_hash = None      # sha256 hex of passkey - used to filter peers
aes_key = None        # 32 bytes for AES encryption


def derive_key(passkey):
    return hashlib.sha256(passkey.encode()).digest()


def encrypt_file(filepath, key):
    iv = get_random_bytes(16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    with open(filepath, "rb") as f:
        data = f.read()
    encrypted = cipher.encrypt(pad(data, AES.block_size))
    enc_path = filepath + ".enc"
    with open(enc_path, "wb") as f:
        f.write(iv + encrypted)
    return enc_path


def decrypt_file(enc_path, key, out_path):
    with open(enc_path, "rb") as f:
        raw = f.read()
    iv = raw[:16]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = unpad(cipher.decrypt(raw[16:]), AES.block_size)
    with open(out_path, "wb") as f:
        f.write(decrypted)


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


MY_IP = get_local_ip()
MY_NAME = args.name if args.name else socket.gethostname()
if FLASK_PORT != 5000:
    MY_NAME = f"{MY_NAME}:{FLASK_PORT}"


def broadcast_presence():
    """Broadcast our existence every 3s. Only if we're in a room."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    while True:
        if room_hash is not None:
            try:
                msg = json.dumps({
                    "type": "HELLO",
                    "ip": MY_IP,
                    "name": MY_NAME,
                    "port": FLASK_PORT,
                    "room_hash": room_hash  # peers filter by this - rooms magic!
                }).encode()
                sock.sendto(msg, ("<broadcast>", DISCOVERY_PORT))
                sock.sendto(msg, ("127.0.0.1", DISCOVERY_PORT))  # local testing
            except Exception as e:
                print(f"Broadcast error: {e}")
        time.sleep(3)


def listen_for_peers():
    """Listen for broadcasts, only accept peers with matching room_hash."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", DISCOVERY_PORT))
    sock.settimeout(2)

    while True:
        try:
            data, addr = sock.recvfrom(1024)
            msg = json.loads(data.decode())

            if msg.get("type") != "HELLO":
                continue

            peer_ip = msg.get("ip")
            peer_port = msg.get("port", 5000)
            peer_room_hash = msg.get("room_hash")
            peer_key = f"{peer_ip}:{peer_port}"
            my_key = f"{MY_IP}:{FLASK_PORT}"

            if peer_key == my_key:
                continue
            if room_hash is None:
                continue
            # THE ROOMS MAGIC - only add peer if same passkey hash /*type shi*/
            if peer_room_hash != room_hash:
                continue

            with peers_lock:
                discovered_peers[peer_key] = {
                    "ip": peer_ip,
                    "name": msg.get("name", "Unknown"),
                    "port": peer_port,
                    "last_seen": time.time()
                }
        except socket.timeout:
            pass
        except Exception as e:
            print(f"Listen error: {e}")

        with peers_lock:
            now = time.time()
            dead = [k for k, v in discovered_peers.items() if now - v["last_seen"] > 10]
            for k in dead:
                del discovered_peers[k]


threading.Thread(target=broadcast_presence, daemon=True).start()
threading.Thread(target=listen_for_peers, daemon=True).start()


# ---- Flask Routes ----

@app.route("/")
def index():
    if room_passkey is None:
        return redirect(url_for("setup"))
    if not session.get("authenticated"):
        return redirect(url_for("login"))
    return render_template("index.html", my_ip=MY_IP, my_name=MY_NAME, room_name=room_name)


@app.route("/setup", methods=["GET", "POST"])
def setup():
    """Create a room - first time setup"""
    global room_name, room_passkey, room_hash, aes_key
    if request.method == "POST":
        name = request.form.get("room_name", "").strip()
        passkey = request.form.get("passkey", "").strip()
        if len(name) < 2:
            return render_template("setup.html", error="Room name needs at least 2 chars")
        if len(passkey) < 4:
            return render_template("setup.html", error="Passkey needs at least 4 chars")
        room_name = name
        room_passkey = passkey
        room_hash = hashlib.sha256(passkey.encode()).hexdigest()
        aes_key = derive_key(passkey)
        session["authenticated"] = True
        print(f"Room '{room_name}' created | hash prefix: {room_hash[:8]}...")
        return redirect(url_for("index"))
    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Join existing room with passkey"""
    if request.method == "POST":
        passkey = request.form.get("passkey", "")
        if hashlib.sha256(passkey.encode()).hexdigest() == room_hash:
            session["authenticated"] = True
            return redirect(url_for("index"))
        return render_template("login.html", room_name=room_name, error="Wrong passkey bro")
    return render_template("login.html", room_name=room_name)


@app.route("/logout")
def logout():
    session.pop("authenticated", None)
    return redirect(url_for("login"))


@app.route("/ping")
def ping():
    """Peers call this to verify we exist and are in the same room"""
    incoming_hash = request.args.get("room_hash")
    if incoming_hash != room_hash:
        return jsonify({"ok": False}), 403
    return jsonify({"ok": True, "name": MY_NAME, "ip": MY_IP})


@app.route("/peers")
def get_peers():
    with peers_lock:
        peers_list = [
            {"ip": v["ip"], "name": v["name"], "port": v["port"]}
            for v in discovered_peers.values()
        ]
    return jsonify({"peers": peers_list, "my_ip": MY_IP, "my_name": MY_NAME, "room": room_name})


@app.route("/add_peer", methods=["POST"])
def add_peer_manually():
    """Manual peer add by IP - fallback when UDP broadcast is blocked (college WiFi lol)"""
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401

    import requests as req_lib
    data = request.json or {}
    peer_ip = data.get("ip", "").strip()
    peer_port = int(data.get("port", 5000))

    if not peer_ip:
        return jsonify({"error": "No IP provided"}), 400

    try:
        resp = req_lib.get(
            f"http://{peer_ip}:{peer_port}/ping",
            params={"room_hash": room_hash},
            timeout=5
        )
        rdata = resp.json()
        if resp.status_code == 200 and rdata.get("ok"):
            peer_key = f"{peer_ip}:{peer_port}"
            with peers_lock:
                discovered_peers[peer_key] = {
                    "ip": peer_ip,
                    "name": rdata.get("name", peer_ip),
                    "port": peer_port,
                    "last_seen": time.time()
                }
            return jsonify({"success": True, "name": rdata.get("name")})
        elif resp.status_code == 403:
            return jsonify({"error": "That device is in a different room!"}), 403
        else:
            return jsonify({"error": "Something went wrong"}), 400
    except Exception as e:
        return jsonify({"error": f"Can't reach {peer_ip}:{peer_port} — is the app running there?"}), 500


@app.route("/send", methods=["POST"])
def send_file_route():
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400

    target_ip = request.form.get("target_ip")
    target_port = int(request.form.get("target_port", FLASK_PORT))
    if not target_ip:
        return jsonify({"error": "No target IP"}), 400

    file = request.files["file"]
    filename = file.filename
    temp_path = os.path.join(UPLOAD_FOLDER, f"temp_{uuid.uuid4()}_{filename}")
    file.save(temp_path)

    enc_path = encrypt_file(temp_path, aes_key)
    os.remove(temp_path)

    import requests as req_lib
    try:
        with open(enc_path, "rb") as f:
            response = req_lib.post(
                f"http://{target_ip}:{target_port}/receive",
                files={"file": (filename + ".enc", f, "application/octet-stream")},
                data={
                    "filename": filename,
                    "sender_ip": MY_IP,
                    "sender_name": MY_NAME,
                    "room_hash": room_hash
                },
                timeout=300
            )
        os.remove(enc_path)
        if response.status_code == 200:
            return jsonify({"success": True})
        return jsonify({"error": f"Peer rejected: {response.text}"}), 400
    except Exception as e:
        if os.path.exists(enc_path):
            os.remove(enc_path)
        return jsonify({"error": f"Failed: {str(e)}"}), 500


@app.route("/receive", methods=["POST"])
def receive_file():
    incoming_hash = request.form.get("room_hash")
    if incoming_hash != room_hash:
        return "Wrong room — go away", 403
    if "file" not in request.files:
        return "No file", 400

    original_filename = request.form.get("filename", "received_file")
    sender_name = request.form.get("sender_name", "Unknown")

    enc_file = request.files["file"]
    enc_path = os.path.join(UPLOAD_FOLDER, f"enc_{uuid.uuid4()}.enc")
    enc_file.save(enc_path)

    out_path = os.path.join(UPLOAD_FOLDER, original_filename)
    if os.path.exists(out_path):
        name, ext = os.path.splitext(original_filename)
        out_path = os.path.join(UPLOAD_FOLDER, f"{name}_{int(time.time())}{ext}")

    try:
        decrypt_file(enc_path, aes_key, out_path)
        os.remove(enc_path)
        print(f"Received '{original_filename}' from {sender_name}")
        return jsonify({"success": True}), 200
    except Exception as e:
        os.remove(enc_path)
        return f"Decryption failed: {e}", 500


@app.route("/files")
def list_files():
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401
    files = []
    for fname in os.listdir(UPLOAD_FOLDER):
        fpath = os.path.join(UPLOAD_FOLDER, fname)
        if os.path.isfile(fpath) and not fname.endswith(".enc"):
            files.append({"name": fname, "size": os.path.getsize(fpath), "modified": os.path.getmtime(fpath)})
    files.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify({"files": files})


@app.route("/download/<filename>")
def download_file(filename):
    if not session.get("authenticated"):
        return redirect(url_for("login"))
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)


@app.route("/delete/<filename>", methods=["DELETE"])
def delete_file(filename):
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401
    fpath = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(fpath):
        os.remove(fpath)
        return jsonify({"success": True})
    return jsonify({"error": "File not found"}), 404


if __name__ == "__main__":
    print(f"\n⚡ LAN Transfer running!")
    print(f"   IP    : {MY_IP}")
    print(f"   Open  : http://{MY_IP}:{FLASK_PORT}")
    print(f"   Local : http://localhost:{FLASK_PORT}")
    if FLASK_PORT != 5000:
        print(f"   ⚠️  Port {FLASK_PORT} — local test mode")
    print()
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False)
