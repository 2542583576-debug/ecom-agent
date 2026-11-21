import json
import urllib.request
import urllib.error
from pathlib import Path


def load_env(path=".env"):
    config = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip().strip('"').strip("'")
    return config


config = load_env()

api_key = config.get("BAILIAN_API_KEY", "").strip()
base_url = config.get("BAILIAN_BASE_URL", "").rstrip("/")
model = config.get("BAILIAN_MODEL", "").strip()

if not api_key.startswith("sk-ws-") or "***" in api_key or len(api_key) < 30:
    raise ValueError("Key 格式异常，请检查 .env")

payload = {
    "model": model,
    "messages": [
        {"role": "user", "content": "只回复OK"}
    ],
    "max_tokens": 20
}

request = urllib.request.Request(
    base_url + "/chat/completions",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json"
    },
    method="POST"
)

try:
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    print("调用成功：", result["choices"][0]["message"]["content"])

except urllib.error.HTTPError as error:
    print("HTTP 错误：", error.code)
    print(error.read().decode("utf-8", "ignore")[:500])

except Exception as error:
    print("调用失败：", type(error).__name__)
    print(str(error)[:300])
