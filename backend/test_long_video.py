#!/usr/bin/env python3
"""
Test script for long video processing in practice mode.
This script tests the optimized movement detection and clip extraction for videos longer than 20 minutes.
"""

import sys
import os
from pathlib import Path

# Add the current directory to Python path
sys.path.append(str(Path(__file__).parent))

from processing.practice_mode import (
    detect_movement_frames,
    extract_practice_clips,
    analyze_cricket_practice_session,
    get_video_duration
)

def test_long_video_processing():
    """Test long video processing capabilities."""
    print("🧪 Testing Long Video Processing Capabilities")
    print("=" * 50)
    
    # Test video path (replace with your actual long video)
    test_video = "uploads/test_long_video.mp4"  # Change this to your video path
    
    if not os.path.exists(test_video):
        print(f"❌ Test video not found: {test_video}")
        print("Please place a test video in the uploads directory or update the path.")
        return
    
    try:
        # Get video duration
        duration = get_video_duration(test_video)
        print(f"📹 Video duration: {duration:.2f} seconds ({duration/60:.1f} minutes)")
        
        if duration < 600:
            print("⚠️  This is not a long video (< 10 minutes). For best testing, use a 20+ minute video.")
        
        # Test movement detection with optimized parameters
        print("\n🔍 Testing Movement Detection...")
        segments = detect_movement_frames(
            video_path=test_video,
            movement_threshold=0.015,  # Optimized for long videos
            min_movement_duration=0.3,
            padding_before=0.5,
            padding_after=2.0
        )
        
        print(f"✅ Movement detection complete. Found {len(segments)} segments")
        
        if segments:
            print(f"📊 First 3 segments:")
            for i, (start, end) in enumerate(segments[:3]):
                print(f"   Segment {i+1}: {start:.2f}s to {end:.2f}s (duration: {end-start:.2f}s)")
            
            # Test clip extraction
            print("\n✂️  Testing Clip Extraction...")
            output_dir = "outputs/test_long_video"
            clip_paths = extract_practice_clips(
                video_path=test_video,
                segments=segments[:5],  # Test with first 5 segments
                output_dir=output_dir,
                practice_type="batting"
            )
            
            print(f"✅ Clip extraction complete. Created {len(clip_paths)} clips")
            
            # Test full analysis
            print("\n🎯 Testing Full Cricket Analysis...")
            result = analyze_cricket_practice_session(
                video_path=test_video,
                output_dir=output_dir,
                practice_type="batting",
                mode="clips"  # Use clips mode for testing
            )
            
            print(f"✅ Full analysis complete:")
            print(f"   Status: {result['status']}")
            print(f"   Segments: {result['total_segments']}")
            print(f"   Efficiency: {result['efficiency_percentage']:.1f}%")
            print(f"   Output files: {len(result['output_files'])}")
            
        else:
            print("⚠️  No movement segments detected. This might indicate:")
            print("   - Video has very little movement")
            print("   - Movement threshold too high")
            print("   - Video quality issues")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_long_video_processing() 