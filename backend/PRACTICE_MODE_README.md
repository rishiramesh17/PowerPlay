# 🏏 PowerPlay Practice Mode

Practice Mode automatically detects movement in practice session videos and extracts relevant clips, removing empty footage between actions.

## 🚀 Features

- **Automatic Movement Detection** - Uses computer vision to detect when players are active
- **Smart Clip Extraction** - Extracts clips with configurable padding before/after movement
- **Empty Footage Removal** - Automatically cuts out boring/empty sections
- **Two Output Modes**:
  - **Individual Clips** - Separate MP4 files for each action
  - **Compiled Highlights** - Single video with all actions concatenated

## 📊 How It Works

1. **Frame Analysis** - Analyzes video frames for movement using frame differencing
2. **Movement Detection** - Identifies segments where significant movement occurs
3. **Smart Padding** - Adds configurable time before/after each movement segment
4. **Clip Extraction** - Uses FFmpeg to extract clean clips without re-encoding
5. **Segment Merging** - Combines overlapping/adjacent segments for efficiency

## ⚙️ Configuration Parameters

- **`movement_threshold`** (0.01 - 0.1): Sensitivity of movement detection
  - Lower values = More sensitive (detects smaller movements)
  - Higher values = Less sensitive (only major movements)
  - **Recommended**: 0.02 for cricket practice

- **`min_movement_duration`** (0.1 - 2.0 seconds): Minimum movement duration
  - **Recommended**: 0.5 seconds for cricket actions

- **`padding_before`** (0.0 - 2.0 seconds): Time before movement starts
  - **Recommended**: 1.0 second to capture setup

- **`padding_after`** (1.0 - 6.0 seconds): Time after movement ends
  - **Recommended**: 4.0 seconds to capture follow-through

## 🎯 Use Cases

### Cricket Practice Sessions
- **Batting Practice**: Detects each shot with setup and follow-through
- **Bowling Practice**: Captures run-up, delivery, and follow-through
- **Fielding Practice**: Tracks movement during drills and catches

### Other Sports
- **Tennis**: Serve, rally, and movement between points
- **Basketball**: Shots, dribbling, and defensive movements
- **Soccer**: Kicks, runs, and ball control

## 🔧 API Usage

### Endpoint: `POST /practice-mode`

```bash
curl -X POST "http://localhost:8000/practice-mode" \
  -F "video=@practice_session.mp4" \
  -F "mode=clips" \
  -F "movement_threshold=0.02" \
  -F "min_movement_duration=0.5" \
  -F "padding_before=1.0" \
  -F "padding_after=4.0"
```

### Parameters
- `video` or `youtube_url`: Video source
- `mode`: "clips" or "highlights"
- `movement_threshold`: Movement sensitivity (0.01-0.1)
- `min_movement_duration`: Minimum movement time (seconds)
- `padding_before`: Time before movement (seconds)
- `padding_after`: Time after movement (seconds)

## 📁 Output Structure

```
outputs/
└── practice_mode/
    ├── practice_clip_000.mp4    # Individual clips
    ├── practice_clip_001.mp4
    ├── practice_clip_002.mp4
    └── practice_highlights.mp4  # Compiled version
```

## 🧪 Testing

Run the test script to see practice mode in action:

```bash
cd backend
python test_practice_mode.py
```

This will:
1. Test movement detection on your video
2. Extract practice clips
3. Compile highlights
4. Show performance metrics

## 📈 Performance Tips

### For Faster Processing
- **Lower `frame_skip`** in code (default: 5)
- **Higher `movement_threshold`** (less sensitive)
- **Shorter videos** (practice sessions vs full matches)

### For Better Quality
- **Lower `movement_threshold`** (more sensitive)
- **Longer `padding_after`** (capture more follow-through)
- **Higher video quality** input

## 🔍 Troubleshooting

### No Movement Detected
- **Lower `movement_threshold`** (try 0.01)
- **Check video quality** and lighting
- **Verify video contains practice actions**

### Too Many Segments
- **Increase `movement_threshold`** (try 0.05)
- **Increase `min_movement_duration`** (try 1.0)
- **Check for camera shake or background movement**

### Segments Too Short
- **Increase `min_movement_duration`** (try 1.0-2.0)
- **Increase `padding_before/after`** for longer clips

## 🎬 Example Workflow

1. **Record Practice Session** - 30 minutes of batting practice
2. **Upload to Practice Mode** - Use movement threshold 0.02
3. **Get Individual Clips** - 15-20 clips of 5-8 seconds each
4. **Review Each Shot** - Analyze technique, timing, form
5. **Share Highlights** - Compile best shots into highlight reel

## 🚀 Future Enhancements

- **Action Classification** - Distinguish between batting/bowling/fielding
- **Quality Scoring** - Rate each action based on movement patterns
- **Player Tracking** - Follow specific players in team practice
- **Real-time Processing** - Live movement detection during practice

---

**Practice Mode transforms hours of practice footage into focused, actionable clips in minutes!** 🏏⚡ 