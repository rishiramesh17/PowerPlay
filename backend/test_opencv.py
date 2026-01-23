import cv2

video_path = "cricketclippers.mp4"  

cap = cv2.VideoCapture(video_path)

if not cap.isOpened():
    print(f"❌ Could not open video: {video_path}")
else:
    print(f"✅ Successfully opened video: {video_path}")
    # Optional: check FPS and frame count
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"FPS: {fps}, Frame count: {frame_count}")

cap.release()