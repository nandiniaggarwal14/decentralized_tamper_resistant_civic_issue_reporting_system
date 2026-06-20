import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

IPFS_STORAGE_DIR = PROJECT_ROOT / "ipfs_storage"
IPFS_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Pinata Config
PINATA_JWT = os.getenv("PINATA_JWT", "").strip()
PINATA_API_KEY = os.getenv("PINATA_API_KEY", "").strip()
PINATA_API_SECRET = os.getenv("PINATA_API_SECRET", "").strip()
PINATA_GATEWAY = os.getenv("PINATA_GATEWAY", "https://gateway.pinata.cloud").strip()

def _get_auth_headers() -> dict:
    if PINATA_JWT:
        return {"Authorization": f"Bearer {PINATA_JWT}"}
    elif PINATA_API_KEY and PINATA_API_SECRET:
        return {
            "pinata_api_key": PINATA_API_KEY,
            "pinata_secret_api_key": PINATA_API_SECRET
        }
    return {}

def is_pinata_configured() -> bool:
    return bool(PINATA_JWT) or (bool(PINATA_API_KEY) and bool(PINATA_API_SECRET))

def generate_cid(content_bytes: bytes) -> str:
    """Generate a mock IPFS CID (SHA256 hash prefixed with Qm). Used if Pinata fails/is offline."""
    hash_str = hashlib.sha256(content_bytes).hexdigest()
    return f"Qm{hash_str[:44]}"

def store_file(file_bytes: bytes, filename: str) -> str:
    """Stores file in local cache AND Pins to Pinata (returns Pinata CID if active)."""
    # 1. Local simulator cache (fallback)
    local_cid = generate_cid(file_bytes)
    cid_dir = IPFS_STORAGE_DIR / local_cid
    cid_dir.mkdir(parents=True, exist_ok=True)
    file_path = cid_dir / filename
    file_path.write_bytes(file_bytes)
    
    metadata = {
        "cid": local_cid,
        "type": "file",
        "filename": filename,
        "size": len(file_bytes)
    }
    with open(cid_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4)

    # 2. Upload to Pinata
    if is_pinata_configured():
        try:
            url = "https://api.pinata.cloud/pinning/pinFileToIPFS"
            headers = _get_auth_headers()
            files = {
                "file": (filename, file_bytes)
            }
            payload = {
                "pinataMetadata": json.dumps({"name": filename})
            }
            response = requests.post(url, files=files, data=payload, headers=headers, timeout=15)
            if response.status_code == 200:
                pinata_cid = response.json().get("IpfsHash")
                if pinata_cid:
                    # Update local cache directory name or symlink if we want, but returning the Pinata CID is sufficient.
                    # Copy metadata to Pinata CID directory locally to ensure retrieval
                    pinata_dir = IPFS_STORAGE_DIR / pinata_cid
                    pinata_dir.mkdir(parents=True, exist_ok=True)
                    (pinata_dir / filename).write_bytes(file_bytes)
                    metadata["cid"] = pinata_cid
                    with open(pinata_dir / "metadata.json", "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=4)
                    return pinata_cid
            else:
                print(f"Pinata file upload failed: {response.text}")
        except Exception as e:
            print(f"Pinata file upload exception: {e}")

    return local_cid

def store_json(data: Any, type_label: str = "data") -> str:
    """Stores JSON in local cache AND Pins to Pinata (returns Pinata CID if active)."""
    # 1. Local simulator cache (fallback)
    json_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
    local_cid = generate_cid(json_bytes)
    cid_dir = IPFS_STORAGE_DIR / local_cid
    cid_dir.mkdir(parents=True, exist_ok=True)
    
    with open(cid_dir / "data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        
    metadata = {
        "cid": local_cid,
        "type": "json",
        "label": type_label,
        "size": len(json_bytes)
    }
    with open(cid_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4)

    # 2. Pin JSON to Pinata
    if is_pinata_configured():
        try:
            url = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
            headers = _get_auth_headers()
            headers["Content-Type"] = "application/json"
            payload = {
                "pinataContent": data,
                "pinataMetadata": {"name": type_label}
            }
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code == 200:
                pinata_cid = response.json().get("IpfsHash")
                if pinata_cid:
                    pinata_dir = IPFS_STORAGE_DIR / pinata_cid
                    pinata_dir.mkdir(parents=True, exist_ok=True)
                    with open(pinata_dir / "data.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=4)
                    metadata["cid"] = pinata_cid
                    with open(pinata_dir / "metadata.json", "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=4)
                    return pinata_cid
            else:
                print(f"Pinata JSON upload failed: {response.text}")
        except Exception as e:
            print(f"Pinata JSON upload exception: {e}")

    return local_cid

def get_ipfs_data(cid: str) -> Any:
    """Fetch content of stored JSON from local cache first, otherwise fall back to Pinata Gateway."""
    # Try local cache
    json_path = IPFS_STORAGE_DIR / cid / "data.json"
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
            
    # Try fetching from Pinata Gateway
    if is_pinata_configured():
        try:
            gateway_url = f"{PINATA_GATEWAY}/ipfs/{cid}"
            response = requests.get(gateway_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Save locally for future calls
                cid_dir = IPFS_STORAGE_DIR / cid
                cid_dir.mkdir(parents=True, exist_ok=True)
                with open(cid_dir / "data.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                return data
        except Exception as e:
            print(f"Failed to fetch CID {cid} from gateway: {e}")
            
    return None

def get_ipfs_file_path(cid: str) -> Optional[Path]:
    """Get path to local file copy of CID."""
    cid_dir = IPFS_STORAGE_DIR / cid
    if cid_dir.exists():
        metadata_path = cid_dir / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            if metadata.get("type") == "file":
                filename = metadata.get("filename")
                if filename:
                    file_path = cid_dir / filename
                    if file_path.exists():
                        return file_path
    return None
