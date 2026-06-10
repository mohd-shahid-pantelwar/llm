import hashlib

def file_hash(content: bytes):
    return hashlib.sha256(content).hexdigest()