from typing import Optional, Tuple
import requests, os, re, sys, logging, argparse, json, zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from urllib.parse import urlsplit

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
            f"MD5 {resp['apk']['baseApkMd5']}",
            f"https://api.ppaooq.com/v11/apps/{resp['packageId']}/download",
        )

    def fetch_full(self) -> dict:
        resp = self.get(f"https://api.qqaoop.com/store/v11/apps/{self.app_id}")
        resp.raise_for_status()
        resp = resp.json()
        assert resp["code"] == 200, resp
        return resp["data"]


class PlainHTTP(requests.Session):
    urls: list

    def __init__(self, *urls: str):
        super().__init__()
        self.urls = list(urls)

    def version_tag(self, resp: requests.Response) -> str:
        etag = resp.headers.get("ETag", None)
        if etag:
            return f"ETag {etag}"
        path = urlsplit(resp.url).path
        version = re.search(r"_v(\d+(?:_\d+)*)", path)
        if version:
            return f"Version {version.group(1)}"
        if path.endswith(".apk"):
            return f"URL {path}"
        modified = resp.headers.get("Last-Modified", None)
        length = resp.headers.get("Content-Range", "").rpartition("/")[2]
        length = length or resp.headers.get("Content-Length", None)
        assert modified and length, f"no version marker found for {resp.url}"
        return f"Modified {modified} {length}"

    def probe(self, url: str) -> Tuple[str, str]:
        with self.get(url, stream=True, headers={"Range": "bytes=0-0"}) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            assert "html" not in content_type, (
                f"{url} resolved to a landing page ({content_type}), not a package"
            )
            return self.version_tag(resp), resp.url

    def fetch(self, retries=3) -> Tuple[str, str]:
        """hash, url"""
        for url in self.urls:
            for attempt in range(retries):
                try:
                    return self.probe(url)
                except Exception as e:
                    logger.warning(f"failed to fetch {url}: {e}")
                    if attempt < retries - 1:
                        logger.warning(f"retrying {url}...")
        raise AssertionError(f"none of {self.urls} resolved to a package")


def soruce(region: str) -> requests.Session:  # hash, url
    # fmt: off
    match region:
        case "jp":
            return QooApp(9038)
        case "en":
            return QooApp(18337)
        case "cn":
            return PlainHTTP("https://ugapk.com/djogd", "https://ugapk.com/dS6rR")
        case "tw":
            return QooApp(18298)
        case "kr":
            return QooApp(20082)
    # fmt: on


def cmd(*command):
    cmd = " ".join(command)
    logger.info(f"running command: cmd")
    return os.system(cmd)


def fetch(region: str) -> Optional[str]:
    CWD = lambda *a: os.path.abspath(os.path.join(region, *a))
    os.makedirs(CWD(), exist_ok=True)
    try:
        src = soruce(region)
        new_hash, url = src.fetch()
    except Exception as e:
        logger.error(f"failed metadata fetch on {region}: {e}")
        return None

    try:
        if os.path.exists(CWD("package_hash")):
            with open(CWD("package_hash"), "r") as f:
                old_hash = f.read().strip()
                if old_hash == new_hash:
                    logger.info(f"hash unchanged on {region}: {old_hash}. skipping.")
                    return None
                else:
                    logger.info(f"hash changed on {region}: {old_hash} -> {new_hash}.")
    except Exception as e:
        logger.error(f"failed to read hash file on {region}: {e}")
        return None

    try:
        os.makedirs(CWD(".temp"), exist_ok=True)

        api_data = src.fetch_full() if hasattr(src, "fetch_full") else None
        downloads = [("base.apk", url)]
        if api_data and api_data.get("splitApks"):
            for s in api_data["splitApks"]:
                downloads.append((s["signature"].split("-")[0] + ".apk", s["url"]))

        def download_file(name, dl_url, dest):
            logger.info(f"downloading {name} for {region}")
            with src.get(dl_url, stream=True) as r:
                r.raise_for_status()
                expected = int(r.headers.get("Content-Length", 0))
                written = 0
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        written += f.write(chunk)
            assert not expected or written == expected, (
                f"truncated download of {name} on {region}: {written}/{expected} bytes"
            )
            return dest

        xapk_path = CWD(".temp", f"{region}.apk")
        part_path = xapk_path + ".part"
        if api_data and len(downloads) > 1:
            manifest = {
                "xapk_version": 2,
                "package_name": api_data["packageId"],
                "name": api_data["appName"],
                "version_code": str(api_data["apk"]["versionCode"]),
                "version_name": api_data["apk"]["versionName"],
                "min_sdk_version": str(api_data["apk"]["sdkVersion"]),
                "split_apks": [
                    {"file": n, "id": n.replace(".apk", "")} for n, _ in downloads
                ],
            }
            with zipfile.ZipFile(part_path, "w", zipfile.ZIP_STORED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))
                for name, dl_url in downloads:
                    split = download_file(name, dl_url, CWD(".temp", name))
                    zf.write(split, name)
                    os.remove(split)
        else:
            download_file("base.apk", url, part_path)
        os.replace(part_path, xapk_path)
    except Exception as e:
        logger.error(f"failed to download {region}: {e}")
        return None

    return new_hash


def apphash(region: str) -> bool:
    CWD = lambda *a: os.path.abspath(os.path.join(region, *a))
    if not os.path.exists(CWD(".temp", f"{region}.apk")) and not os.path.exists(
        CWD(".temp", f"{region}.xapk")
    ):
        logger.error(f"apk/xapk not found on {region}.")
        return False
    from sssekai.entrypoint.apphash import main_apphash

    class NamedDict(dict):
        def __getattribute__(self, name: str):
            try:
                return super().__getattribute__(name)
            except AttributeError:
                return self.get(name, None)

    apk_src = (
        CWD(".temp", f"{region}.xapk")
        if os.path.exists(CWD(".temp", f"{region}.xapk"))
        else CWD(".temp", f"{region}.apk")
    )

    results = dict()
    for fmt, out in (("json", "apphash.json"), ("markdown", "apphash.md")):
        buf = StringIO()
        try:
            with redirect_stdout(buf):
                main_apphash(
                    NamedDict({"apk_src": apk_src, "format": fmt, "deep": False})
                )
        except Exception as e:
            logger.error(f"failed to pull {fmt} hashes on {region}: {e}")
            return False
        results[out] = buf.getvalue()
        if not results[out].strip().strip("{}").strip():
            logger.error(f"no hashes found on {region}. is the package usable?")
            return False

    for out, content in results.items():
        with open(CWD(out), "w", encoding="utf-8") as f:
            f.write(content)
    return True


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

    new_hashes = dict()
    if not args.skip_download:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {region: executor.submit(fetch, region) for region in REGIONS}
        for region, future in futures.items():
            try:
                new_hashes[region] = future.result()
            except Exception as e:
                logger.error(f"failed to download {region}: {e}")

    for region in REGIONS:
        CWD = lambda *a: os.path.abspath(os.path.join(region, *a))
        if not apphash(region):
            continue
        if not new_hashes.get(region):
            continue
        try:
            with open(CWD("package_hash"), "w") as f:
                f.write(new_hashes[region])
            logger.info(f"hash file updated on {region}: {new_hashes[region]}.")
        except Exception as e:
            logger.error(f"failed to update hash file on {region}: {e}")


if __name__ == "__main__":
    __main__()
