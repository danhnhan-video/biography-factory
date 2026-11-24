"""Gửi thông báo về điện thoại qua ứng dụng ntfy (miễn phí). Không cấu hình thì bỏ qua."""
import os, requests

def send(title: str, message: str, link: str | None = None, tags=("movie_camera",), priority: int = 3):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    print(f"[thông báo] {title} — {message}")
    if not topic:
        return
    body = {"topic": topic, "title": title, "message": message, "tags": list(tags), "priority": priority}
    if link:
        body["click"] = link
    try:
        requests.post("https://ntfy.sh/", json=body, timeout=15)
    except Exception as e:
        print("  (không gửi được thông báo:", e, ")")
