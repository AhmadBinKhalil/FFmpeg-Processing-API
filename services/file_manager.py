"""
Temporary file management service.
Handles creating, storing, and cleaning up temporary files for processing.
"""

import os
import uuid
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict
from fastapi import UploadFile


class FileManager:
    """Manages temporary files for FFmpeg processing."""
    
    def __init__(self, base_temp_dir: str = None):
        """
        Initialize the file manager.
        
        Args:
            base_temp_dir: Base directory for temp files. Uses system temp if not provided.
        """
        self.base_temp_dir = base_temp_dir or tempfile.gettempdir()
    
    def create_session_dir(self) -> str:
        """
        Create a unique temporary directory for a processing session.
        
        Returns:
            Path to the created directory.
        """
        session_id = str(uuid.uuid4())
        session_dir = os.path.join(self.base_temp_dir, "ffmpeg_processor", session_id)
        os.makedirs(session_dir, exist_ok=True)
        return session_dir
    
    async def save_upload_files(
        self, 
        files: List[UploadFile], 
        session_dir: str
    ) -> Dict[str, str]:
        """
        Save uploaded files to the session directory.
        
        Args:
            files: List of uploaded files.
            session_dir: Directory to save files to.
            
        Returns:
            Dictionary mapping placeholder names to file paths.
            e.g., {"input": "/path/to/file.mp4", "input1": "/path/to/file1.mp4"}
        """
        input_files = {}
        
        for i, file in enumerate(files):
            # Sanitize filename to prevent path traversal
            safe_filename = self._sanitize_filename(file.filename)
            file_path = os.path.join(session_dir, safe_filename)
            
            # Save the file
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)
            
            # Map to placeholder names
            if len(files) == 1:
                input_files["input"] = file_path
            else:
                input_files[f"input{i + 1}"] = file_path
                if i == 0:
                    input_files["input"] = file_path  # Also map first file to {input}
        
        return input_files
    
    def create_output_path(self, session_dir: str, extension: str = ".mp4") -> str:
        """
        Create a path for the output file.
        
        Args:
            session_dir: Session directory.
            extension: Output file extension (with dot).
            
        Returns:
            Path for the output file.
        """
        # Ensure extension starts with a dot
        if not extension.startswith("."):
            extension = f".{extension}"
        
        output_filename = f"output_{uuid.uuid4().hex[:8]}{extension}"
        return os.path.join(session_dir, output_filename)
    
    def cleanup_session(self, session_dir: str) -> None:
        """
        Remove the session directory and all its contents.
        
        Args:
            session_dir: Directory to clean up.
        """
        try:
            if os.path.exists(session_dir):
                shutil.rmtree(session_dir)
        except Exception as e:
            # Log but don't raise - cleanup is best effort
            print(f"Warning: Failed to cleanup session directory {session_dir}: {e}")
    
    def copy_font_to_session(self, font_path: str, session_dir: str) -> str:
        """
        Copy a font file to the session directory.
        This avoids path escaping issues with spaces in paths.
        
        Args:
            font_path: Path to the source font file.
            session_dir: Session directory to copy to.
            
        Returns:
            Path to the copied font file in the session directory.
        """
        if not os.path.exists(font_path):
            raise FileNotFoundError(f"Font file not found: {font_path}")
        
        font_filename = os.path.basename(font_path)
        dest_path = os.path.join(session_dir, font_filename)
        shutil.copy2(font_path, dest_path)
        return dest_path
    
    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize a filename to prevent path traversal attacks.
        
        Args:
            filename: Original filename.
            
        Returns:
            Sanitized filename.
        """
        if not filename:
            return f"file_{uuid.uuid4().hex[:8]}"
        
        # Get just the filename, no path components
        safe_name = Path(filename).name
        
        # Remove any remaining problematic characters
        safe_name = safe_name.replace("..", "").replace("/", "_").replace("\\", "_")
        
        # Ensure we have a valid filename
        if not safe_name or safe_name in (".", ".."):
            safe_name = f"file_{uuid.uuid4().hex[:8]}"
        
        return safe_name
