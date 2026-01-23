from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
import shutil
import json
import os

from processing.detect_player import detect_player_in_video
from processing.track_player import track_player
from processing.compile_clips import compile_highlight

app = FastAPI()

# CORS so frontend can talk to backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to your frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Temporary storage for uploads
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/process-video")
async def process_video(video: UploadFile = File(...), playerData: str = Form(...)):
    # Parse player info from frontend
    player_data = json.loads(playerData)

    # Save uploaded video
    temp_path = os.path.join(UPLOAD_DIR, video.filename)
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(video.file, buffer)

    # --- Detection & Highlight Generation Logic ---
    detections = detect_player_in_video(temp_path, player_data)
    tracked_segments = track_player(temp_path, detections)
    highlight_path = compile_highlight(temp_path, tracked_segments)

    return {
        "status": "success",
        "highlight_path": highlight_path,
        "player_data": player_data
    }