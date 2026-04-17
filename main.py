# /// script
# dependencies = [
#   "requests",
# ]
# ///

import ctypes
import ipaddress
import json
import locale
import logging
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "autologin.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)

LAST_SKIP_REASON = None
LAST_WAIT_REASON = None

EXCLUDED_INTERFACE_KEYWORDS = (
    "mihomo",
    "vmware",
    "vethernet",
    "hyper-v",
    "virtual",
    "virtualbox",
    "loopback",
    "bluetooth",
    "wi-fi direct",
    "本地连接*",
)

PREFERRED_INTERFACE_KEYWORDS = (
    "wlan",
    "wi-fi",
    "wireless",
    "无线",
)

JSONP_RE = re.compile(r"^[^(]+\((.*)\)\s*;?\s*$", re.S)

DEFAULT_CONFIG = {
    "username": "",
    "password": "",
    "isp_suffix": "@cmccn",
    "isp_suffix_options": ["@cmccn", "@unicomn", "@telecomn"],
    "portal_host": "portal.csu.edu.cn:802",
    "online_check_url": "http://www.baidu.com",
    "test_timeout": 5,
    "login_timeout": 10,
    "check_interval": 10,
    "retry_interval": 30,
    "preferred_ip_prefix": "100.",
    "allowed_ssids": ["CSU-Student", "CSU-WIFI"],
    "hide_console": True,
}

SUBPROCESS_KWARGS = {}
if sys.platform == "win32":
    SUBPROCESS_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


def hide_console_window() -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        logging.debug("隐藏控制台失败", exc_info=True)


def show_message_box(title: str, message: str, flags: int = 0x10) -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, flags)
    except Exception:
        logging.debug("弹窗提示失败", exc_info=True)


def ensure_config_exists() -> None:
    if CONFIG_PATH.exists():
        return
    CONFIG_PATH.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    raise RuntimeError(f"已生成默认配置，请先填写 {CONFIG_PATH.name} 中的账号和密码后再运行。")


def load_config() -> dict:
    ensure_config_exists()
    config = DEFAULT_CONFIG | json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    if not str(config.get("username", "")).strip() or not str(config.get("password", "")).strip():
        raise RuntimeError(f"{CONFIG_PATH.name} 中的 username 或 password 为空，请填写后再运行。")

    if not config.get("allowed_ssids"):
        raise RuntimeError(f"{CONFIG_PATH.name} 中的 allowed_ssids 不能为空。")

    return config


console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logging.getLogger().addHandler(console_handler)

CONFIG: dict = {}
USERNAME = ""
PASSWORD = ""
ISP_SUFFIX = "@cmccn"
PORTAL_HOST = "portal.csu.edu.cn:802"
ONLINE_CHECK_URL = "http://www.baidu.com"
TEST_TIMEOUT = 5
LOGIN_TIMEOUT = 10
CHECK_INTERVAL = 10
RETRY_INTERVAL = 30
PREFERRED_IP_PREFIX = "100."
ALLOWED_SSIDS: set[str] = set()


def apply_config(config: dict) -> None:
    global CONFIG
    global USERNAME, PASSWORD, ISP_SUFFIX, PORTAL_HOST, ONLINE_CHECK_URL
    global TEST_TIMEOUT, LOGIN_TIMEOUT, CHECK_INTERVAL, RETRY_INTERVAL
    global PREFERRED_IP_PREFIX, ALLOWED_SSIDS

    CONFIG = config
    USERNAME = str(config["username"]).strip()
    PASSWORD = str(config["password"])
    ISP_SUFFIX = str(config["isp_suffix"]).strip() or "@cmccn"
    PORTAL_HOST = str(config["portal_host"]).strip()
    ONLINE_CHECK_URL = str(config["online_check_url"]).strip()
    TEST_TIMEOUT = int(config["test_timeout"])
    LOGIN_TIMEOUT = int(config["login_timeout"])
    CHECK_INTERVAL = int(config["check_interval"])
    RETRY_INTERVAL = int(config["retry_interval"])
    PREFERRED_IP_PREFIX = str(config["preferred_ip_prefix"]).strip()
    ALLOWED_SSIDS = {str(ssid).strip() for ssid in config["allowed_ssids"] if str(ssid).strip()}


def is_valid_ipv4(ip: str) -> bool:
    try:
        ipaddress.IPv4Address(ip)
        return True
    except ValueError:
        return False


def is_excluded_interface(name: str) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in EXCLUDED_INTERFACE_KEYWORDS)


def iter_ipconfig_ipv4():
    preferred_encodings = []
    for encoding in (locale.getpreferredencoding(False), "mbcs", "gbk", "cp936", "utf-8"):
        if encoding and encoding not in preferred_encodings:
            preferred_encodings.append(encoding)

    result = subprocess.run(
        ["ipconfig", "/all"],
        capture_output=True,
        check=True,
        **SUBPROCESS_KWARGS,
    )

    stdout = None
    for encoding in preferred_encodings:
        try:
            stdout = result.stdout.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if stdout is None:
        stdout = result.stdout.decode(preferred_encodings[0], errors="ignore")

    current_iface = None
    for raw_line in stdout.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            continue

        is_interface_header = (
            raw_line
            and not raw_line[:1].isspace()
            and stripped.endswith(":")
            and ("adapter " in stripped.lower() or "适配器" in stripped)
        )
        if is_interface_header:
            current_iface = stripped[:-1]
            continue

        if "IPv4 地址" in stripped or "IPv4 Address" in stripped:
            match = re.search(r":\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", stripped)
            if match and current_iface:
                yield current_iface, match.group(1)


def run_command_text(*command: str) -> str:
    preferred_encodings = []
    for encoding in (locale.getpreferredencoding(False), "mbcs", "gbk", "cp936", "utf-8"):
        if encoding and encoding not in preferred_encodings:
            preferred_encodings.append(encoding)

    result = subprocess.run(command, capture_output=True, check=True, **SUBPROCESS_KWARGS)
    for encoding in preferred_encodings:
        try:
            return result.stdout.decode(encoding)
        except UnicodeDecodeError:
            continue
    return result.stdout.decode(preferred_encodings[0], errors="ignore")


def score_candidate(interface_name: str, ip: str) -> tuple[int, int, int]:
    prefix_score = 3 if ip.startswith(PREFERRED_IP_PREFIX) else 0
    iface_lower = interface_name.lower()
    preferred_iface_score = 2 if any(k in iface_lower for k in PREFERRED_INTERFACE_KEYWORDS) else 0
    excluded_penalty = -5 if is_excluded_interface(interface_name) else 0
    return prefix_score, preferred_iface_score, excluded_penalty


def get_preferred_ip(debug: bool = False) -> tuple[str | None, str | None]:
    candidates = []

    for interface_name, ip in iter_ipconfig_ipv4():
        if not is_valid_ipv4(ip) or ip.startswith("127."):
            continue
        candidates.append((interface_name, ip, score_candidate(interface_name, ip)))

    if debug:
        print("=== ipconfig 候选 IPv4 ===")
        for interface_name, ip, score in candidates:
            print(f"{interface_name} -> {ip} score={score}")
        print("=" * 50)

    if not candidates:
        raise RuntimeError("未从 ipconfig /all 中解析到可用 IPv4。")

    best_name, best_ip, _ = max(candidates, key=lambda item: item[2])
    if best_ip.startswith(PREFERRED_IP_PREFIX):
        return best_ip, best_name
    return None, f"{best_name} -> {best_ip}"


def get_current_wifi_ssid() -> str | None:
    try:
        output = run_command_text("netsh", "wlan", "show", "interfaces")
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        logging.warning("获取当前 Wi-Fi SSID 失败: %s", exc)
        return None

    connected = False
    current_ssid = None
    for raw_line in output.splitlines():
        stripped = raw_line.strip()
        if not stripped or ":" not in stripped:
            continue

        key, value = [part.strip() for part in stripped.split(":", 1)]
        key_lower = key.lower()

        if key_lower == "state" or key == "状态":
            connected = value.lower() == "connected" or value == "已连接"
            continue

        if key_lower == "ssid" or key == "SSID":
            if value and not value.lower().startswith("bssid"):
                current_ssid = value

    if connected:
        return current_ssid
    return None


def should_attempt_login() -> bool:
    global LAST_SKIP_REASON

    ssid = get_current_wifi_ssid()
    if ssid in ALLOWED_SSIDS:
        LAST_SKIP_REASON = None
        return True

    if ssid is None:
        skip_reason = ("disconnected", None)
        if LAST_SKIP_REASON != skip_reason:
            logging.info("当前未连接 Wi-Fi，跳过校园网登录")
    else:
        skip_reason = ("ssid", ssid)
        if LAST_SKIP_REASON != skip_reason:
            logging.info("当前 Wi-Fi 为 %s，不在允许列表中，跳过校园网登录", ssid)

    LAST_SKIP_REASON = skip_reason
    return False


def get_login_ip() -> str | None:
    global LAST_WAIT_REASON

    preferred_ip, interface_name = get_preferred_ip(debug=False)
    if preferred_ip and interface_name:
        LAST_WAIT_REASON = None
        logging.info("已选中校园网 IP: %s (%s)", preferred_ip, interface_name)
        return preferred_ip

    wait_reason = ("missing_preferred_ip", interface_name)
    if LAST_WAIT_REASON != wait_reason:
        logging.info("已连接校园 Wi-Fi，但尚未获取 %s.x IP，当前候选为 %s，等待重试", PREFERRED_IP_PREFIX.rstrip("."), interface_name)
    LAST_WAIT_REASON = wait_reason
    return None


def build_online_data_url(ip: str) -> str:
    encoded_password = quote(PASSWORD, safe="")
    return (
        f"https://{PORTAL_HOST}/eportal/portal/Custom/online_data"
        f"?callback=dr1003"
        f"&username={USERNAME}"
        f"&password={encoded_password}"
        f"&ip={ip}"
        f"&wlan_ac_name="
        f"&wlan_ac_ip="
        f"&mac=000000000000"
        f"&login_method=undefined"
        f"&jsVersion=4.1.3"
        f"&v={int(time.time() * 1000)}"
        f"&lang=zh"
    )


def build_login_url(ip: str) -> str:
    encoded_password = quote(PASSWORD, safe="")
    user_account = f",0,{USERNAME}{ISP_SUFFIX}"
    encoded_user_account = quote(user_account, safe="")

    return (
        f"https://{PORTAL_HOST}/eportal/portal/login"
        f"?callback=dr1004"
        f"&login_method=1"
        f"&user_account={encoded_user_account}"
        f"&user_password={encoded_password}"
        f"&wlan_user_ip={ip}"
        f"&wlan_user_ipv6="
        f"&wlan_user_mac=000000000000"
        f"&wlan_ac_ip="
        f"&wlan_ac_name="
        f"&jsVersion=4.1.3"
        f"&terminal_type=1"
        f"&lang=zh-cn"
        f"&v={int(time.time() * 1000)}"
        f"&lang=zh"
    )


def parse_jsonp(text: str) -> dict:
    match = JSONP_RE.match(text.strip())
    payload = match.group(1) if match else text
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {"raw": text}


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"https://{PORTAL_HOST}/",
            "Accept": "*/*",
        }
    )
    return session


def is_online(session: requests.Session) -> bool:
    try:
        response = session.get(ONLINE_CHECK_URL, timeout=TEST_TIMEOUT, allow_redirects=True)
        return response.ok
    except requests.RequestException:
        return False


def query_online_data(session: requests.Session, local_ip: str) -> None:
    try:
        response = session.get(build_online_data_url(local_ip), timeout=LOGIN_TIMEOUT)
        logging.info("online_data 状态码: %s", response.status_code)
        if response.ok:
            logging.info("online_data 响应: %s", parse_jsonp(response.text))
    except requests.RequestException as exc:
        logging.warning("online_data 查询失败: %s", exc)


def login(session: requests.Session, local_ip: str) -> bool:
    try:
        login_response = session.get(build_login_url(local_ip), timeout=LOGIN_TIMEOUT)
        logging.info("login 状态码: %s", login_response.status_code)
        parsed = parse_jsonp(login_response.text)
        logging.info("login 响应: %s", parsed)

        if login_response.ok and "error" not in login_response.text.lower():
            time.sleep(3)
            return True

        query_online_data(session, local_ip)
        return False
    except requests.RequestException as exc:
        logging.error("登录请求异常: %s", exc)
        query_online_data(session, local_ip)
        return False


def main_loop() -> None:
    session = create_session()
    retry_count = 0
    while True:
        if not should_attempt_login():
            time.sleep(CHECK_INTERVAL)
            continue

        if is_online(session):
            retry_count = 0
            time.sleep(CHECK_INTERVAL)
            continue

        local_ip = get_login_ip()
        if not local_ip:
            time.sleep(CHECK_INTERVAL)
            continue

        retry_count += 1
        logging.warning("检测到断网，开始第 %s 次重试登录...", retry_count)
        if login(session, local_ip):
            retry_count = 0
            logging.info("登录成功")
        else:
            logging.error("登录失败，%s 秒后重试", RETRY_INTERVAL)
        time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    try:
        loaded_config = load_config()
        apply_config(loaded_config)

        if CONFIG.get("hide_console", True):
            hide_console_window()

        logging.info("校园网自动登录守护程序启动")
        main_loop()
    except Exception as exc:
        logging.exception("程序启动失败")
        show_message_box("CSU Auto Login", str(exc))
        raise SystemExit(1)
