# FFmpeg Processing API

A robust, FastAPI-based service designed to process video and audio files dynamically using FFmpeg commands. This project allows users to upload files, apply complex FFmpeg transformations via a flexible command API, and retrieve the processed results immediately.

> [!NOTE]
> **Free to Use & Edit**: This project is open for use and modification.

## 🚀 Features

- **Dynamic Processing**: Execute custom FFmpeg commands on uploaded files.
- **Multiple Inputs**: Support for processing multiple input files simultaneously.
- **Bundled Assets**: Includes bundled fonts (e.g., OpenSans) for easy text overlays.
- **Safety Checks**: Basic validation to prevent common command injection attacks (see Security section).
- **Docker Ready**: Fully containerized for easy deployment (runs in POSIX/Linux mode).
- **Auto-Cleanup**: Temporary sessions are automatically cleaned up after processing.
- **Two Execution Modes**:
    1.  **Standard Enpoint**: Pass a string for direct shell execution (great for simple commands).
    2.  **JSON Arguments**: Pass a JSON array to bypass the shell entirely (perfect for quotes/newlines).

> [!TIP]
> **Docker/Linux Users**: When sending commands via `curl` or valid shell strings, ensure you escape characters according to POSIX standards. Newlines can usually be passed as `\n` or `\\\n` depending on your client's quoting.

## 🛠️ Setup & Installation

### Option 1: Docker (Recommended)

1.  **Clone the repository**.
2.  **Run with Docker Compose**:
    ```bash
    docker-compose up --build
    ```
3.  The API will be available at `http://localhost:8000`.

### Option 2: Local Development

**Prerequisites**: Python 3.9+ and **FFmpeg** installed on your system path.

1.  **Create a virtual environment**:
    ```bash
    python -m venv .venv
    # Windows
    .venv\Scripts\activate
    # Linux/Mac
    source .venv/bin/activate
    ```
2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Run the server**:
    ```bash
    uvicorn main:app --reload
    ```

## ⚙️ Configuration

Control the application behavior using environment variables (or `.env` file):

| Variable | Description | Default |
| :--- | :--- | :--- |
| `TEMP_DIR` | Directory for temporary file storage | System Temp |
| `MAX_FILE_SIZE_MB` | Maximum allowed upload size per file (MB) | `500` |
| `FFMPEG_TIMEOUT_SECONDS` | Timeout for FFmpeg operations (seconds) | `300` |

## 📖 Usage Guide

Failed requests return standard HTTP error codes. Successful processing returns the file as a downloadable attachment.

### Endpoint: `POST /process`

**Parameters:**
- `files`: One or more files to upload.
- `command`: The FFmpeg command.
    - **String**: Executed via system shell (e.g., `-i {input} ...`).
    - **JSON List**: Executed directly via subprocess (e.g., `["-i", "{input}", ...]`). Recommended for complex text/escaping.
- `output_extension`: (Optional) Desired output extension (e.g., `.mp4`, `.mp3`).
- `execution_mode`: (Optional) Parsing strategy.
    - `auto` (default): Tries to parse as JSON, falls back to shell string.
    - `json`: Forces JSON parsing (errors `400` if invalid).
    - `shell`: Forces shell string execution.

**Command Placeholders:**
- `{input}`: The first uploaded file.
- `{input2}`, `{input3}`...: Subsequent files.
- `{output}`: The system-generated output path.
- `{font}`: Path to the bundled OpenSans font.

### Examples

**1. Add a Watermark**
```bash
-i {input} -vf drawtext=fontfile={font}:text='MyWatermark':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2 -c:v libx264 {output}
```

**2. Convert to MP4 (Fast Preset)**
```bash
-i {input} -c:v libx264 -preset fast {output}
```

**3. Extract Audio (MP3)**
```bash
-i {input} -vn -acodec mp3 {output}
```
*(Note: set `output_extension` to `.mp3`)*

**4. Resize to 720p**
```bash
-i {input} -vf scale=-1:720 -c:v libx264 {output}
```

**5. Trim Video (Start at 00:00:10, Duration 5s)**
```bash
-i {input} -ss 00:00:10 -t 5 -c:v libx264 -c:a copy {output}
```

**6. Create GIF (Scale 320px width)**
```bash
-i {input} -vf "fps=10,scale=320:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" -loop 0 {output}
```
*(Note: set `output_extension` to `.gif`)*

**7. Remove Audio (Mute)**
```bash
-i {input} -c:v copy -an {output}
```

**8. Increase Volume (150%)**
```bash
-i {input} -filter:a "volume=1.5" -c:v copy {output}
```

**9. Grayscale Video**
```bash
-i {input} -vf hue=s=0 -c:a copy {output}
```

**10. Rotate 90 Degrees Clockwise**
```bash
-i {input} -vf "transpose=1" -c:a copy {output}
```

**11. Compress Video (CRF 28)**
```bash
-i {input} -vcodec libx264 -crf 28 {output}
```

**12. Merge Video and Audio (Two Inputs)**
*Requires uploading video as file #1 and audio as file #2*
```bash
-i {input} -i {input2} -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 {output}
```

**13. Generate Thumbnail (at 5 seconds)**
```bash
-i {input} -ss 00:00:05 -vframes 1 {output}
```
*(Note: set `output_extension` to `.jpg`)*

**14. Speed Up Video (2x)**
```bash
-i {input} -filter:v "setpts=0.5*PTS" -filter:a "atempo=2.0" {output}
```

**15. Fade In (Video Only, 1s)**
```bash
-i {input} -vf "fade=t=in:st=0:d=1" -c:a copy {output}
```

**16. Darkened Background with Multiline Text (Complex)**
*For complex text with newlines, using **JSON format** is highly recommended to avoid escaping hell.*

**Option A: JSON Format (Recommended)**
```json
["-i", "{input}", "-vf", "eq=brightness=-0.2, drawtext=fontfile={font}:text='Line 1\nLine 2':fontcolor=white:fontsize=h/30:x=(w-text_w)/2:y=(h-text_h)/2", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "{output}"]
```

**Option B: Standard Shell String**
*Requires 4 backslashes (`\\\\n`) to pass a literal newline through the shell.*
```bash
-i {input} -vf "eq=brightness=-0.2, drawtext=fontfile={font}:text='Line 1\\\\nLine 2':fontcolor=white:fontsize=h/30:x=(w-text_w)/2:y=(h-text_h)/2" -an -c:v libx264 -pix_fmt yuv420p {output}
```

## ⚠️ Security Considerations

> [!WARNING]
> This service executes shell commands based on user input.

While basic sanitization is implemented (blocking dangerous characters like `;`, `|`, `` ` ``), this service **should not be exposed publicly** without additional security layers. It is intended for internal use or behind a secure gateway.

## 🔜 Next Steps & Roadmap

To actively improve this project for production use, the following steps are recommended:

-   **Security**: Implement API Key authentication to restrict access.
-   **Async Processing**: Integrate **Celery** with **Redis** to offload long-running encoding tasks to the background, preventing HTTP timeouts.
-   **Storage**: Implement a configurable retention policy for local storage (e.g., keep files for 3 hours) and add optional **S3/Cloud Storage** support for persistence.
-   **API**: Develop an endpoint to **list processed files**, returning metadata such as submission time, processing duration, and current status.
-   **Testing**: Add a comprehensive suite of **Pytest** unit and integration tests.
-   **Observability**: Implement robust structured logging. (Optional: Add Prometheus/Grafana for real-time metrics).

---
*Generated by Antigravity*
