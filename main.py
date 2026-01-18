"""
FastAPI + FFmpeg File Processing API

Upload files, process them with FFmpeg commands, and get the results.
"""

import os
import json
import mimetypes
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from services.file_manager import FileManager
from services.ffmpeg_processor import FFmpegProcessor


# Configuration from environment variables
TEMP_DIR = os.getenv("TEMP_DIR") or None
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "500"))
FFMPEG_TIMEOUT = int(os.getenv("FFMPEG_TIMEOUT_SECONDS", "300"))

# Bundled fonts directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(BASE_DIR, "fonts")
DEFAULT_FONT = os.path.join(FONTS_DIR, "OpenSans.ttf")

# Valid output extensions
VALID_EXTENSIONS = {
    "mp4", "webm", "mkv", "avi", "mov", "flv", "wmv", "m4v",  # Video
    "mp3", "wav", "aac", "flac", "ogg", "m4a", "wma",  # Audio
    "gif", "png", "jpg", "jpeg", "webp", "bmp", "tiff"  # Image
}

# Initialize services
file_manager = FileManager(base_temp_dir=TEMP_DIR)
ffmpeg_processor = FFmpegProcessor(timeout_seconds=FFMPEG_TIMEOUT)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    print("🚀 FFmpeg Processing API starting up...")
    print(f"📁 Temp directory: {file_manager.base_temp_dir}")
    print(f"📦 Max file size: {MAX_FILE_SIZE_MB} MB")
    print(f"⏱️  FFmpeg timeout: {FFMPEG_TIMEOUT} seconds")
    yield
    # Shutdown
    print("👋 FFmpeg Processing API shutting down...")


app = FastAPI(
    title="FFmpeg Processing API",
    description="Upload files, process them with FFmpeg, and get the results.",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "ffmpeg-processor"}


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "FFmpeg Processing API",
        "version": "1.0.0",
        "endpoints": {
            "POST /process": "Upload files and process with FFmpeg",
            "GET /health": "Health check"
        },
        "usage": {
            "command_format": "Use {input} for inputs, {output} for output, {font} for bundled font",
            "placeholders": {
                "{input}": "Single input file (or {input1}, {input2} for multiple)",
                "{output}": "Output file path (auto-generated)",
                "{font}": "Path to bundled OpenSans font"
            },
            "examples": [
                {
                    "description": "Add watermark text",
                    "command": "-i {input} -vf drawtext=fontfile={font}:text='WaterMark':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2 -c:v libx264 {output}"
                },
                {
                    "description": "Darken + watermark",
                    "command": "-i {input} -vf eq=brightness=-0.3,drawtext=fontfile={font}:text='WaterMark':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2 -an -c:v libx264 {output}"
                },
                {
                    "description": "Convert to MP4",
                    "command": "-i {input} -c:v libx264 -preset fast {output}"
                },
                {
                    "description": "Extract audio as MP3",
                    "command": "-i {input} -vn -acodec mp3 -ab 192k {output}"
                }
            ]
        }
    }


@app.post("/process")
async def process_files(
    files: List[UploadFile] = File(..., description="Files to process"),
    command: str = Form(..., description="FFmpeg command template"),
    output_extension: Optional[str] = Form(None, description="Output file extension (auto-detected if not provided)")
):
    """
    Process uploaded files with FFmpeg.
    
    **Command Format:**
    - Use `{input}` for single file input, or `{input1}`, `{input2}`, etc. for multiple files
    - Use `{output}` for the output file path
    - Use `{font}` for the bundled OpenSans font path
    
    **Example Commands:**
    - Add watermark: `-i {input} -vf drawtext=fontfile={font}:text='Text':fontcolor=white:fontsize=48 {output}`
    - Convert to MP4: `-i {input} -c:v libx264 -preset fast {output}`
    - Extract audio: `-i {input} -vn -acodec mp3 {output}`
    
    **Returns:**
    The processed file as a downloadable attachment.
    """
    # Validate files
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    
    # Check file sizes
    for file in files:
        # Read file to check size (we'll need to read it anyway)
        content = await file.read()
        size_mb = len(content) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            raise HTTPException(
                status_code=413,
                detail=f"File '{file.filename}' exceeds maximum size of {MAX_FILE_SIZE_MB} MB"
            )
        # Reset file position for later reading
        await file.seek(0)
    
    # Validate command
    if not command or not command.strip():
        raise HTTPException(status_code=400, detail="Command is required")
    
    # Create session directory
    session_dir = file_manager.create_session_dir()
    
    # DEBUG: Log raw command
    print(f"DEBUG: Raw command received (repr): {repr(command)}")
    print(f"DEBUG: Raw command received (str): {command}")
    
    try:
        # Save uploaded files
        input_files = await file_manager.save_upload_files(files, session_dir)
        
        # Determine output extension - validate if provided, otherwise auto-detect
        ext = None
        if output_extension:
            # Clean and validate the extension
            clean_ext = output_extension.lower().strip().lstrip(".")
            if clean_ext in VALID_EXTENSIONS:
                ext = f".{clean_ext}"
        
        # Fall back to auto-detection if no valid extension provided
        if not ext:
            ext = ffmpeg_processor.detect_output_extension(command)
        
        # Create output path
        output_path = file_manager.create_output_path(session_dir, ext)
        
        # If command uses {font}, copy font to session dir (avoids path escaping issues)
        session_font_path = None
        if "{font}" in command:
            try:
                session_font_path = file_manager.copy_font_to_session(DEFAULT_FONT, session_dir)
            except FileNotFoundError as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        # Parse command: check if it's a JSON list (for direct subprocess execution)
        parsed_command = command
        try:
            if command.strip().startswith("["):
                possible_list = json.loads(command)
                if isinstance(possible_list, list):
                    parsed_command = possible_list
                    print("DEBUG: Command parsed as JSON list (Subprocess Mode)")
        except json.JSONDecodeError as e:
            print(f"DEBUG: JSON decode failed ({e}). Falling back to Shell Mode.")
            pass  # Not valid JSON, treat as string (Shell Mode)
            
        # Parse and validate command
        try:
            args = ffmpeg_processor.parse_command(
                parsed_command, input_files, output_path, 
                font_path=session_font_path
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        # Execute FFmpeg
        success, message, output_content = await ffmpeg_processor.execute(args, output_path)
        
        if not success:
            raise HTTPException(status_code=500, detail=message)
        
        # Determine content type
        content_type, _ = mimetypes.guess_type(f"file{ext}")
        if not content_type:
            content_type = "application/octet-stream"
        
        # Generate output filename
        if len(files) == 1:
            base_name = os.path.splitext(files[0].filename)[0]
        else:
            base_name = "processed"
        output_filename = f"{base_name}_processed{ext}"
        
        return Response(
            content=output_content,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{output_filename}"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")
    finally:
        # Always cleanup
        file_manager.cleanup_session(session_dir)


@app.post("/process-json")
async def process_files_json(
    files: List[UploadFile] = File(..., description="Files to process"),
    command: str = Form(..., description="FFmpeg command template"),
    output_extension: Optional[str] = Form(None, description="Output file extension")
):
    """
    Process files and return result info as JSON (without the file content).
    Useful for testing or when you just want to verify processing works.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    
    session_dir = file_manager.create_session_dir()
    
    try:
        input_files = await file_manager.save_upload_files(files, session_dir)
        
        # Determine output extension - validate if provided, otherwise auto-detect
        ext = None
        if output_extension:
            clean_ext = output_extension.lower().strip().lstrip(".")
            if clean_ext in VALID_EXTENSIONS:
                ext = f".{clean_ext}"
        if not ext:
            ext = ffmpeg_processor.detect_output_extension(command)
        
        output_path = file_manager.create_output_path(session_dir, ext)
        
        # If command uses {font}, copy font to session dir
        session_font_path = None
        if "{font}" in command:
            try:
                session_font_path = file_manager.copy_font_to_session(DEFAULT_FONT, session_dir)
            except FileNotFoundError as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        # Parse command: check if it's a JSON list (for direct subprocess execution)
        parsed_command = command
        try:
            if command.strip().startswith("["):
                possible_list = json.loads(command)
                if isinstance(possible_list, list):
                    parsed_command = possible_list
        except json.JSONDecodeError as e:
            print(f"DEBUG: JSON decode failed ({e}). Falling back to Shell Mode.")
            pass

        try:
            args = ffmpeg_processor.parse_command(
                parsed_command, input_files, output_path,
                font_path=session_font_path
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        success, message, output_content = await ffmpeg_processor.execute(args, output_path)
        
        if not success:
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": message}
            )
        
        return {
            "success": True,
            "message": message,
            "output_size_bytes": len(output_content) if output_content else 0,
            "output_extension": ext,
            "input_files_count": len(files)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")
    finally:
        file_manager.cleanup_session(session_dir)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
