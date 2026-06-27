import os
import shutil
import tempfile
import uuid
import mimetypes
from pathlib import Path
from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form, Request, Response, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# --- Configuration ---
ROOT_DIR = Path("D:/").resolve()
USERNAME = "admin"
PASSWORD = "use_your_own_password"

# --- FastAPI Setup ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS = {}

# --- Helper: Secure Path Sanitizer ---
def get_safe_path(raw_path: str = "") -> Path:
    """Ensures the user cannot access files outside the root directory."""
    if not raw_path:
        return ROOT_DIR

    raw_path = raw_path.replace("\\", "/").lstrip("/")
    if ":" in raw_path:
        raw_path = raw_path.split(":", 1)[-1].lstrip("/")

    full_path = (ROOT_DIR / raw_path).resolve()

    try:
        full_path.relative_to(ROOT_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied: Path traversal detected")

    return full_path

# --- Authentication Dependency ---
def auth_dependency(request: Request):
    token = request.cookies.get("session_token")
    if not token or token not in SESSIONS:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return token

# --- Serve Frontend ---
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

# --- Login Endpoint ---
@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...), response: Response = None):
    if username == USERNAME and password == PASSWORD:
        token = str(uuid.uuid4())
        SESSIONS[token] = username
        response.set_cookie(key="session_token", value=token, httponly=True, samesite="lax", max_age=86400)
        return {"status": "ok"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

# --- Logout ---
@app.post("/logout")
async def logout(response: Response, token=Depends(auth_dependency)):
    SESSIONS.pop(token, None)
    response.delete_cookie("session_token")
    return {"status": "ok"}

# --- API: List Directory ---
@app.get("/api/list")
async def list_directory(path: str = "", _=Depends(auth_dependency)):
    target_dir = get_safe_path(path)

    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target_dir.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    items = []
    try:
        for item in target_dir.iterdir():
            is_dir = item.is_dir()
            items.append({
                "name": item.name,
                "path": str(item.relative_to(ROOT_DIR)).replace("\\", "/"),
                "is_dir": is_dir,
                "size": 0 if is_dir else item.stat().st_size,
                "modified": item.stat().st_mtime
            })
    except PermissionError:
        pass

    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return items

# --- API: Download (with Preview vs Force Download) ---
@app.get("/api/download")
async def download_file(
    path: str, 
    disposition: str = "attachment",
    background_tasks: BackgroundTasks = None, 
    _=Depends(auth_dependency)
):
    target = get_safe_path(path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if target.is_file():
        media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        headers = {"Content-Disposition": f'{disposition}; filename="{target.name}"'}
        return FileResponse(path=target, media_type=media_type, headers=headers)

    elif target.is_dir():
        temp_dir = tempfile.mkdtemp()
        zip_name = f"{target.name}.zip"
        zip_path = Path(temp_dir) / zip_name
        shutil.make_archive(str(zip_path.with_suffix('')), 'zip', root_dir=target.parent, base_dir=target.name)
        if background_tasks is not None:
            background_tasks.add_task(shutil.rmtree, temp_dir)
        return FileResponse(path=zip_path, filename=zip_name, media_type="application/zip")

# --- API: Upload Files (FIXED: path is now Query, not Form) ---
@app.post("/api/upload")
async def upload_files(
    path: str = Query(...),
    files: list[UploadFile] = File(...),
    _=Depends(auth_dependency)
):
    target_dir = get_safe_path(path)

    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(status_code=400, detail="Target directory does not exist")

    uploaded_names = []
    for file in files:
        file_path = target_dir / file.filename
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            uploaded_names.append(file.filename)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to upload {file.filename}: {str(e)}")

    return {"status": "ok", "uploaded": uploaded_names}

# --- API: Create Folder (FIXED: path is now Query, not Form) ---
@app.post("/api/mkdir")
async def create_folder(
    path: str = Query(...),
    folder_name: str = Form(...),
    _=Depends(auth_dependency)
):
    target_dir = get_safe_path(path)
    new_folder = target_dir / folder_name

    if new_folder.exists():
        raise HTTPException(status_code=400, detail="Folder already exists")

    try:
        new_folder.mkdir(parents=True)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- API: Delete ---
@app.delete("/api/delete")
async def delete_item(path: str, _=Depends(auth_dependency)):
    target = get_safe_path(path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    try:
        if target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import socket
    import uvicorn

    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    print("\n" + "=" * 60)
    print("🚀 Personal NAS Server is RUNNING!")
    print("-" * 60)
    print(f"🌐 Open in YOUR browser (this PC):  http://127.0.0.1:8000")
    print(f"📱 Open on OTHER devices (same WiFi): http://{local_ip}:8000")
    print("-" * 60)
    print("⚠️  Keep this terminal window OPEN.")
    print("Press CTRL + C to STOP the server.")
    print("=" * 60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
