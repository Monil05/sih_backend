import os
from fastapi import UploadFile

def save_upload_file_tmp(upload_file: UploadFile, tmp_dir: str = '/tmp') -> str:
    if not upload_file:
        return None
    os.makedirs(tmp_dir, exist_ok=True)
    out_path = os.path.join(tmp_dir, upload_file.filename)
    with open(out_path, 'wb') as f:
        f.write(upload_file.file.read())
    return out_path
