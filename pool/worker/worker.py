import os
import sys
import time
import json
import re
import socket
import platform
import subprocess
import queue
import threading
import urllib.request
import urllib.parse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Default Configuration (can be overridden via environment variables or command-line arguments)
SERVER_URL = os.environ.get("POOL_SERVER_URL", "http://127.0.0.1:8000")
WORKER_NAME = os.environ.get("WORKER_NAME", f"Worker-{socket.gethostname()}")
GPU_MASK = os.environ.get("GPU_MASK", "0")
WORKER_ID = f"{WORKER_NAME}-{int(time.time()) % 10000}"

def http_post(endpoint: str, payload: dict) -> dict:
    url = urllib.parse.urljoin(SERVER_URL, endpoint)
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"❌ HTTP Error connecting to pool server ({url}): {e}")
        return {}

def detect_gpus() -> str:
    try:
        res = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            gpus = [line.strip() for line in res.stdout.strip().split("\n")]
            return ", ".join(gpus)
    except Exception:
        pass
    return "NVIDIA GPU"

def get_binary_path() -> str:
    system = platform.system()
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    
    if system == "Windows":
        bin_path = os.path.join(root_dir, "RCKangaroo.exe")
        if not os.path.exists(bin_path):
            bin_path = os.path.join(root_dir, "x64", "Release", "RCKangaroo.exe")
        if not os.path.exists(bin_path):
            bin_path = os.path.join(root_dir, "build", "Release", "RCKangaroo.exe")
        return bin_path
    else:
        # Linux
        bin_path = os.path.join(root_dir, "rckangaroo")
        if not os.path.exists(bin_path):
            print("⚙️ Compiling RCKangaroo for Linux...")
            build_cmd = "nvcc -O3 -std=c++17 -o rckangaroo RCKangaroo.cpp GpuKang.cpp Ec.cpp utils.cpp CallCubin.cpp RCGpuCore.cu -lcuda -lcudart -lpthread"
            subprocess.run(build_cmd, shell=True, cwd=root_dir, check=True)
        return bin_path

def enqueue_output(out, q):
    for line in iter(out.readline, ''):
        q.put(line)
    out.close()

def main():
    print(f"==================================================")
    print(f"🦘 RCKangaroo Worker Node Initializing")
    print(f"Server URL:  {SERVER_URL}")
    print(f"Worker Name: {WORKER_NAME}")
    print(f"Worker ID:   {WORKER_ID}")
    print(f"OS:          {platform.system()} {platform.release()}")
    
    gpu_info = detect_gpus()
    print(f"GPU Hardware:{gpu_info}")
    
    bin_path = get_binary_path()
    if not os.path.exists(bin_path):
        print(f"❌ Error: RCKangaroo binary not found at: {bin_path}")
        sys.exit(1)
    
    print(f"Binary Path: {bin_path}")
    print(f"==================================================")

    # Register worker with pool server
    reg_resp = http_post("/api/worker/register", {
        "worker_id": WORKER_ID,
        "name": WORKER_NAME,
        "os_info": f"{platform.system()} {platform.release()}",
        "gpu_info": gpu_info
    })
    
    if not reg_resp:
        print("⚠️ Warning: Could not register with pool server. Retrying in background...")

    while True:
        try:
            # Request work chunk
            work = http_post("/api/worker/get_work", {"worker_id": WORKER_ID})
            
            if not work or work.get("status") == "NO_WORK":
                print("💤 No active work jobs from pool server. Sleeping for 5s...")
                time.sleep(5)
                continue
            
            if work.get("status") == "WORK_ASSIGNED":
                chunk_id = work["chunk_id"]
                pubkey = work["pubkey"]
                start_hex = work["start_hex"]
                range_bits = work.get("chunk_bits", work["range_bits"])
                dp_bits = work["dp_bits"]
                max_ops = work.get("max_ops", "3.0")

                print(f"\n🚀 Received Work Unit Chunk: {chunk_id}")
                print(f"   Target Pubkey: {pubkey}")
                print(f"   Start Offset:  {start_hex}")
                print(f"   Range Bits:    {range_bits} bits")
                print(f"   DP Bits:       {dp_bits}")

                # Build executable command line
                cmd = [
                    bin_path,
                    "-gpu", GPU_MASK,
                    "-dp", str(dp_bits),
                    "-range", str(range_bits),
                    "-start", start_hex,
                    "-pubkey", pubkey,
                    "-max", str(max_ops)
                ]

                print(f"   Command: {' '.join(cmd)}")
                
                # Execute process
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=os.path.dirname(bin_path), bufsize=1)
                
                out_q = queue.Queue()
                reader_thread = threading.Thread(target=enqueue_output, args=(proc.stdout, out_q))
                reader_thread.daemon = True
                reader_thread.start()

                current_mhs = 0.0
                last_heartbeat = time.time()
                found_key = None

                while True:
                    # Drain lines from process output
                    while True:
                        try:
                            line = out_q.get_nowait()
                        except queue.Empty:
                            break
                        
                        if line:
                            line_str = line.strip()
                            print(f"[RCK] {line_str}")

                            # Output speed parsing (e.g. "Speed: 14500 MKeys/s" or "Speed: 14.5 GKeys/s")
                            mhs_match = re.search(r'Speed:\s*(\d+(?:\.\d+)?)\s*MKeys', line_str, re.IGNORECASE)
                            if mhs_match:
                                current_mhs = float(mhs_match.group(1))
                            else:
                                ghs_match = re.search(r'Speed:\s*(\d+(?:\.\d+)?)\s*GKeys', line_str, re.IGNORECASE)
                                if ghs_match:
                                    current_mhs = float(ghs_match.group(1)) * 1000.0
                                else:
                                    khs_match = re.search(r'Speed:\s*(\d+(?:\.\d+)?)\s*KKeys', line_str, re.IGNORECASE)
                                    if khs_match:
                                        current_mhs = float(khs_match.group(1)) / 1000.0
                                    else:
                                        # Fallback regexes
                                        fallback_mh = re.search(r'(\d+(?:\.\d+)?)\s*(?:MKeys|MH)', line_str, re.IGNORECASE)
                                        if fallback_mh:
                                            current_mhs = float(fallback_mh.group(1))
                                        fallback_gh = re.search(r'(\d+(?:\.\d+)?)\s*(?:GKeys|GH)', line_str, re.IGNORECASE)
                                        if fallback_gh:
                                            current_mhs = float(fallback_gh.group(1)) * 1000.0

                            # Check for private key solution
                            if "PRIVATE KEY:" in line_str:
                                print(f"\n🎉 FOUND SOLUTION IN OUTPUT: {line_str}")
                                parts = line_str.split("PRIVATE KEY:")
                                if len(parts) >= 2:
                                    found_key = parts[1].strip()

                    # Send periodic heartbeats every 3 seconds
                    if time.time() - last_heartbeat > 3:
                        http_post("/api/worker/heartbeat", {
                            "worker_id": WORKER_ID,
                            "hashrate_mhs": current_mhs
                        })
                        last_heartbeat = time.time()

                    # Exit condition: process ended and output queue drained
                    if proc.poll() is not None and out_q.empty():
                        break

                    time.sleep(0.1)

                # Check if results file was generated
                results_file = os.path.join(os.path.dirname(bin_path), "RESULTS.TXT")
                if os.path.exists(results_file):
                    with open(results_file, "r") as rf:
                        content = rf.read()
                        for rline in content.split("\n"):
                            if "PRIVATE KEY:" in rline:
                                found_key = rline.split("PRIVATE KEY:")[-1].strip()

                if found_key:
                    print(f"🌟 Submitting solution {found_key} for job {work['job_id']}...")
                    http_post("/api/worker/submit_solution", {
                        "worker_id": WORKER_ID,
                        "chunk_id": chunk_id,
                        "pubkey": pubkey,
                        "private_key": found_key
                    })
                else:
                    print(f"✅ Completed chunk {chunk_id}. Requesting next chunk...")

        except KeyboardInterrupt:
            print("\n🛑 Worker interrupted by user. Exiting...")
            break
        except Exception as e:
            print(f"⚠️ Error during execution: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
