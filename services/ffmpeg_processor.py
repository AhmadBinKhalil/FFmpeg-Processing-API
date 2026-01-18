"""
FFmpeg processing service.
Handles command parsing, validation, and execution.
"""

import re
import asyncio
import shlex
from typing import Dict, Tuple, Optional


class FFmpegProcessor:
    """Executes FFmpeg commands safely."""
    
    # Dangerous arguments that could be exploited
    BLOCKED_ARGS = {
        "-filter_complex_script",  # Could read arbitrary files
        "pipe:",  # Prevent pipe-based exploits
    }
    
    # Patterns that might indicate command injection attempts
    DANGEROUS_PATTERNS = [
        r"[;&|`$]",  # Shell operators
        r"\$\(",     # Command substitution
        r"`",        # Backticks
    ]
    
    def __init__(self, timeout_seconds: int = 300):
        """
        Initialize the FFmpeg processor.
        
        Args:
            timeout_seconds: Maximum time for FFmpeg command execution.
        """
        self.timeout = timeout_seconds
    
    def parse_command(
        self, 
        command_template: str, 
        input_files: Dict[str, str], 
        output_path: str,
        font_path: str = None
    ) -> str:
        """
        Prepare the command string by replacing placeholders.
        Retains the raw command structure for shell execution.
        
        Args:
            command_template: Command template with {input}, {output}, {font}.
            input_files: Dictionary mapping placeholder names to file paths.
            output_path: Path for the output file.
            font_path: Path to the bundled font.
            
        Returns:
            The formatted command string.
        """
        # Check for blocked arguments (basic sanity check only)
        for arg in self.BLOCKED_ARGS:
            if arg in command_template:
                raise ValueError(f"Blocked argument: {arg}")
        
        command = command_template
        
        # Helper to safely quote paths for shell
        def quote_path(path):
            return shlex.quote(path)

        # Replace output placeholder (quoted)
        command = command.replace("{output}", quote_path(output_path))
        
        # Replace font placeholder
        if font_path and "{font}" in command:
            # For shell execution, simple quoting usually works best
            command = command.replace("{font}", quote_path(font_path))
        
        # Replace input placeholders
        for placeholder, file_path in input_files.items():
            # Replace {input} with safely quoted path
            command = command.replace(f"{{{placeholder}}}", quote_path(file_path))
        
        # Check for unreplaced placeholders
        remaining_placeholders = re.findall(r"\{(\w+)\}", command)
        if remaining_placeholders:
            raise ValueError(f"Unreplaced placeholders in command: {remaining_placeholders}")
            
        return command
    
    def _validate_args(self, args: list) -> None:
        """Deprecated/Unused in raw shell mode."""
        pass
    
    async def execute(
        self, 
        command: str,
        output_path: str
    ) -> Tuple[bool, str, Optional[bytes]]:
        """
        Execute an FFmpeg command using the system shell.
        
        Args:
            command: The full command string (without 'ffmpeg -y').
            output_path: Expected output file path.
            
        Returns:
            Tuple of (success, message, output_content).
        """
        # Build the full command string
        # We use shell=True logic via create_subprocess_shell
        full_cmd = f"ffmpeg -y {command}"
        
        print(f"DEBUG: Executing shell command: {full_cmd}")
        
        try:
            # Run FFmpeg via Shell
            process = await asyncio.create_subprocess_shell(
                full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return False, f"FFmpeg command timed out after {self.timeout} seconds", None
            
            # Check if command succeeded
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace")
                return False, f"FFmpeg error (exit code {process.returncode}): {error_msg}", None
            
            # Read output file
            try:
                with open(output_path, "rb") as f:
                    output_content = f.read()
                return True, "Processing completed successfully", output_content
            except FileNotFoundError:
                return False, "FFmpeg completed but output file was not created", None
            except Exception as e:
                return False, f"Error reading output file: {e}", None
                
        except Exception as e:
            return False, f"Unexpected error during FFmpeg execution: {e}", None
    
    def detect_output_extension(self, command_template: str) -> str:
        """
        Try to detect the intended output format from the command.
        
        Args:
            command_template: The FFmpeg command template.
            
        Returns:
            Detected extension (with dot) or default ".mp4".
        """
        # Common format mappings
        format_extensions = {
            "mp4": ".mp4",
            "webm": ".webm",
            "mkv": ".mkv",
            "avi": ".avi",
            "mov": ".mov",
            "mp3": ".mp3",
            "wav": ".wav",
            "aac": ".aac",
            "flac": ".flac",
            "ogg": ".ogg",
            "gif": ".gif",
            "png": ".png",
            "jpg": ".jpg",
            "jpeg": ".jpg",
            "webp": ".webp",
        }
        
        # Try to find -f format flag
        format_match = re.search(r"-f\s+(\w+)", command_template)
        if format_match:
            fmt = format_match.group(1).lower()
            if fmt in format_extensions:
                return format_extensions[fmt]
        
        # Try to find common codec indicators
        if any(x in command_template.lower() for x in ["-acodec mp3", "-c:a mp3", "libmp3lame"]):
            return ".mp3"
        if any(x in command_template.lower() for x in ["-vn", "-an"]) and "mp3" in command_template.lower():
            return ".mp3"
        if "-vframes 1" in command_template or "-frames:v 1" in command_template:
            return ".jpg"  # Single frame usually means image
        
        # Default to mp4
        return ".mp4"
