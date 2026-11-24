"""Google Drive qua API bằng refresh token của chính bạn (không cần mở Colab)."""
from __future__ import annotations
import io, json, os, time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

FOLDER = "application/vnd.google-apps.folder"
SCOPES = ["https://www.googleapis.com/auth/drive"]
STATES = ["_inbox", "_dang_lam", "_done", "_loi", "output", "music"]


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


class Drive:
    def __init__(self):
        raw = json.loads(os.environ["GDRIVE_CLIENT_JSON"])
        c = raw.get("installed") or raw.get("web") or raw
        creds = Credentials(None, refresh_token=os.environ["GDRIVE_REFRESH_TOKEN"],
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=c["client_id"], client_secret=c["client_secret"], scopes=SCOPES)
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        self.ids: dict[str, str] = {}

    def _x(self, req):
        for i in range(5):
            try:
                return req.execute(num_retries=3)
            except HttpError as e:
                if e.resp.status in (429, 500, 502, 503) and i < 4:
                    time.sleep(5 * (i + 1)); continue
                raise

    def ls(self, parent, name=None, folder=None):
        q = f"'{parent}' in parents and trashed = false"
        if name:  q += f" and name = '{_q(name)}'"
        if folder is True:  q += f" and mimeType = '{FOLDER}'"
        if folder is False: q += f" and mimeType != '{FOLDER}'"
        out, tok = [], None
        while True:
            r = self._x(self.svc.files().list(q=q, fields="nextPageToken, files(id,name,mimeType,modifiedTime)",
                                              pageToken=tok, orderBy="name", pageSize=200))
            out += r["files"]; tok = r.get("nextPageToken")
            if not tok:
                return out

    def folder(self, name, parent):
        f = self.ls(parent, name, folder=True)
        if f:
            return f[0]["id"]
        return self._x(self.svc.files().create(body={"name": name, "mimeType": FOLDER, "parents": [parent]},
                                               fields="id"))["id"]

    def download(self, fid, path):
        with io.FileIO(path, "wb") as fh:
            d = MediaIoBaseDownload(fh, self.svc.files().get_media(fileId=fid), chunksize=50 * 1024 * 1024)
            done = False
            while not done:
                _, done = d.next_chunk(num_retries=3)

    def upload(self, path, parent):
        name = os.path.basename(path)
        media = MediaFileUpload(path, resumable=True, chunksize=50 * 1024 * 1024)
        old = self.ls(parent, name, folder=False)
        if old:
            return self._x(self.svc.files().update(fileId=old[0]["id"], media_body=media))["id"]
        return self._x(self.svc.files().create(body={"name": name, "parents": [parent]},
                                               media_body=media, fields="id"))["id"]

    def write_text(self, name, text, parent):
        p = f"/tmp/{name}"
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return self.upload(p, parent)

    def move(self, fid, src, dst):
        self._x(self.svc.files().update(fileId=fid, addParents=dst, removeParents=src))

    def init_root(self, name: str):
        """Tìm thư mục gốc (My Drive/DanhNhan) và các thư mục trạng thái."""
        roots = [f for f in self.ls("root", name, folder=True) if self.ls(f["id"], "_inbox", folder=True)]
        if not roots:
            raise SystemExit(f"❌ Không thấy My Drive/{name}/_inbox")
        self.ids["root"] = roots[0]["id"]
        for s in STATES:
            self.ids[s] = self.folder(s, self.ids["root"])
        return self.ids
