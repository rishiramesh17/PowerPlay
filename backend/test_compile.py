import json
from processing.detect_player import detect_player_in_video
from processing.track_player import track_player
from processing.compile_clips import compile_highlight

def test_pipeline():
    video_path = "cricketclippers.mp4"
    player_data = {
        "jersey_number": "7"
    }

    print("Running player detection...")
    segments = detect_player_in_video(video_path, player_data, frame_skip=15, action= "bowling")
    print(f"Detected segments: {segments}")

    print("Tracking player segments...")
    tracked_segments = track_player(video_path, segments)
    print(f"Tracked segments: {tracked_segments}")

    print("Compiling highlight video...")
    highlight_path = compile_highlight(video_path, tracked_segments)
    print(f"Highlight video created at: {highlight_path}")

if __name__ == "__main__":
    test_pipeline()