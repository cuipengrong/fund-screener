"""
服务器同步脚本 — 上传代码并重启 Streamlit
用法: python sync.py
"""

import paramiko
import os
import sys
import time

HOST = "124.223.183.165"
USER = "ubuntu"
PASS = "Cuipeng@0316"
REMOTE_DIR = "/home/ubuntu/fund_screener"
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))


def sync():
    print(f"🔗 Connecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS, timeout=10)

    sftp = ssh.open_sftp()

    # Upload source files (skip cache/cache/pycache)
    skip = {"__pycache__", ".git", "fund_cache.db", "sync.py"}
    uploaded = 0

    def upload_dir(local, remote):
        nonlocal uploaded
        try:
            sftp.mkdir(remote)
        except Exception:
            pass
        for item in os.listdir(local):
            if item in skip or item.startswith("."):
                continue
            lp = os.path.join(local, item)
            rp = f"{remote}/{item}".replace("\\", "/")
            if os.path.isfile(lp):
                sftp.put(lp, rp)
                print(f"  ⬆ {item}")
                uploaded += 1
            elif os.path.isdir(lp):
                upload_dir(lp, rp)

    print("📦 Uploading files...")
    upload_dir(LOCAL_DIR, REMOTE_DIR)
    sftp.close()

    print(f"✅ {uploaded} files uploaded")

    # Restart service
    print("🔄 Restarting service...")
    stdin, stdout, stderr = ssh.exec_command(
        "sudo systemctl restart fund-screener && sleep 3 && "
        "curl -s -o /dev/null -w '%{http_code}' http://localhost:8501",
        timeout=15,
    )
    status = stdout.read().decode().strip()
    err = stderr.read().decode().strip()

    if status == "200":
        print(f"✅ Server OK (HTTP {status})")
        print(f"🌐 http://{HOST}:8501")
    else:
        print(f"⚠️  Server returned HTTP {status}")
        if err:
            print(f"ERR: {err[:200]}")

    ssh.close()


if __name__ == "__main__":
    sync()
