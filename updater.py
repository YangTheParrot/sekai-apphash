from typing import Tuple
import requests, os, sys, logging, argparse, json, zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout

QOOAPP_TOKEN = os.environ.get("QOOAPP_TOKEN", None)
assert QOOAPP_TOKEN, "Environment variable QOOAPP_TOKEN not set."


logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("updater")


class QooApp(requests.Session):
    app_id: int

    def __init__(self, app_int: int):
        super().__init__()
        self.app_id = app_int
        self.headers.update(
            {
                "X-Version-Code": "80608",
                "X-Device-ABIs": "arm64-v8a,armeabi-v7a,x86,x86_64",
                "X-User-Token": QOOAPP_TOKEN,
            }
        )

    def fetch(self) -> Tuple[str, str]:
        """hash, url"""
        resp = self.get(f"https://api.qqaoop.com/store/v11/apps/{self.app_id}")
        resp.raise_for_status()
        resp = resp.json()
        assert resp["code"] == 200, resp
        resp = resp["data"]
        return (
            f'MD5 {resp["apk"]["baseApkMd5"]}',
            f"https://api.ppaooq.com/v11/apps/{resp['packageId']}/download",
        )

    def fetch_full(self) -> dict:
        resp = self.get(f"https://api.qqaoop.com/store/v11/apps/{self.app_id}")
        resp.raise_for_status()
        resp = resp.json()
        assert resp["code"] == 200, resp
        return resp["data"]


class PlainETag(requests.Session):
    url: str

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def fetch(self, retries=5) -> Tuple[str, str]:
        for _ in range(retries):
            try:
                resp = self.get(self.url, stream=True)
                resp.raise_for_status()
                etag = resp.headers.get("ETag", None)
                assert etag, f"ETag not found for {self.url}"
                return f"ETag {etag}", self.url
            except Exception as e:
                logger.warning(f"failed to fetch {self.url}: {e}")
                if _ == retries - 1:
                    raise e
                logger.warning(f"retrying {self.url}...")


def soruce(region: str) -> requests.Session:  # hash, url
    # fmt: off
    match region:
        case "jp": 
            return QooApp(9038)
        case "en":
            return QooApp(18337)
        case "cn":
            return PlainETag("https://ugapk.com/djogd")        
        case "tw":
            return QooApp(18298)
        case "kr":
            return QooApp(20082)
    # fmt: on


def cmd(*command):
    cmd = " ".join(command)
    logger.info(f"running command: cmd")
    return os.system(cmd)


def fetch(region: str):
    CWD = lambda *a: os.path.abspath(os.path.join(region, *a))
    os.makedirs(CWD(), exist_ok=True)
    try:
        src = soruce(region)
        new_hash, url = src.fetch()
    except Exception as e:
        logger.error(f"failed metadata fetch on {region}: {e}")
        return

    try:
        if os.path.exists(CWD("package_hash")):
            with open(CWD("package_hash"), "r") as f:
                old_hash = f.read().strip()
                if old_hash == new_hash:
                    logger.info(f"hash unchanged on {region}: {old_hash}. skipping.")
                    return
                else:
                    logger.info(f"hash changed on {region}: {old_hash} -> {new_hash}.")
    except Exception as e:
        logger.error(f"failed to update hash file on {region}: {e}")
        return

    try:
        os.makedirs(CWD(".temp"), exist_ok=True)

        api_data = src.fetch_full() if hasattr(src, "fetch_full") else None
        downloads = [("base.apk", url)]
        if api_data and api_data.get("splitApks"):
            for s in api_data["splitApks"]:
                downloads.append((s["signature"].split("-")[0] + ".apk", s["url"]))

        def download_bytes(name, dl_url):
            logger.info(f"downloading {name} for {region}")
            with src.get(dl_url, stream=True) as r:
                r.raise_for_status()
                buf = bytearray()
                for chunk in r.iter_content(chunk_size=8192):
                    buf.extend(chunk)
                return bytes(buf)

        xapk_path = CWD(".temp", f"{region}.apk")
        if api_data and len(downloads) > 1:
            manifest = {
                "xapk_version": 2,
                "package_name": api_data["packageId"],
                "name": api_data["appName"],
                "version_code": str(api_data["apk"]["versionCode"]),
                "version_name": api_data["apk"]["versionName"],
                "min_sdk_version": str(api_data["apk"]["sdkVersion"]),
                "split_apks": [{"file": n, "id": n.replace(".apk", "")} for n, _ in downloads],
            }
            with zipfile.ZipFile(xapk_path, "w", zipfile.ZIP_STORED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))
                for name, dl_url in downloads:
                    zf.writestr(name, download_bytes(name, dl_url))
        else:
            with open(xapk_path, "wb") as f:
                f.write(download_bytes("base.apk", url))

    except Exception as e:
        logger.error(f"failed to download {region}: {e}")
        return

    try:
        with open(CWD("package_hash"), "w") as f:
            f.write(new_hash)
            logger.info(f"hash file updated on {region}: {new_hash}.")
    except Exception as e:
        logger.error(f"failed to update hash file on {region}: {e}")
        return


def apphash(region: str):
    CWD = lambda *a: os.path.abspath(os.path.join(region, *a))
    if not os.path.exists(CWD(".temp", f"{region}.apk")):
        logger.error(f"apk not found on {region}.")
        return
    from apphash import main_apphash

    class NamedDict(dict):
        def __getattribute__(self, name: str):
            try:
                return super().__getattribute__(name)
            except AttributeError:
                return self.get(name, None)

    with open(CWD("apphash.json"), "w") as f:
        with redirect_stdout(f):
            main_apphash(
                NamedDict(
                    {
                        "apk_src": CWD(".temp", f"{region}.apk"),
                        "format": "json",
                        "deep": False
                    }
                )
            )

    with open(CWD("apphash.md"), "w") as f:
        with redirect_stdout(f):
            main_apphash(
                NamedDict(
                    {
                        "apk_src": CWD(".temp", f"{region}.apk"),
                        "format": "markdown",
                        "deep": False
                    }
                )
            )


def __main__():
    REGIONS = ["jp", "en", "cn", "tw", "kr"]
    parser = argparse.ArgumentParser("Sekai AppHash updater")
    parser.add_argument(
        "-r",
        "--region",
        type=str,
        default="all",
        choices=REGIONS,
        help="region to update",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="skip downloading the apk and pull hashes immediately",
    )
    args = parser.parse_args()
    if args.region != "all":
        REGIONS = [args.region]

    if not args.skip_download:
        with ThreadPoolExecutor(max_workers=8) as executor:
            for region in REGIONS:
                executor.submit(fetch, region)

    for region in REGIONS:
        apphash(region)


if __name__ == "__main__":
    __main__()
