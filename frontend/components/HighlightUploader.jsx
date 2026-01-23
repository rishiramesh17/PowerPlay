import React, { useState } from "react";
import axios from "axios";

function HighlightUploader() {
  const [videoFile, setVideoFile] = useState(null);
  const [action, setAction] = useState("batting"); // default action
  const [loading, setLoading] = useState(false);
  const [highlightPath, setHighlightPath] = useState(null);

  // Handle file input change
  const handleFileChange = (e) => {
    setVideoFile(e.target.files[0]);
  };

  // Handle button click
  const handleUpload = async () => {
    if (!videoFile) {
      alert("Please select a video file first");
      return;
    }

    const formData = new FormData();
    formData.append("video", videoFile);
    formData.append("playerData", JSON.stringify({ jersey_number: "18" })); // update as needed
    formData.append("action", action); // batting or bowling

    try {
      setLoading(true);
      const response = await axios.post(
        "http://127.0.0.1:8000/process-video",
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      );

      console.log(response.data);
      setHighlightPath(response.data.highlight_path);
    } catch (err) {
      console.error(err);
      alert("Error processing video");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2>Upload Video and Create Highlight</h2>

      <input type="file" accept="video/*" onChange={handleFileChange} />
      <div style={{ marginTop: "10px" }}>
        <button onClick={() => setAction("batting")}>Batting</button>
        <button onClick={() => setAction("bowling")}>Bowling</button>
      </div>

      <div style={{ marginTop: "10px" }}>
        <button onClick={handleUpload} disabled={loading}>
          {loading ? "Processing..." : "Create Highlight"}
        </button>
      </div>

      {highlightPath && (
        <div style={{ marginTop: "10px" }}>
          <a href={highlightPath} target="_blank" rel="noreferrer">
            Download Highlight Video
          </a>
        </div>
      )}
    </div>
  );
}

export default HighlightUploader;