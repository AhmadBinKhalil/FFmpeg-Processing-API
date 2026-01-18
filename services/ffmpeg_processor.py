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
    ) -> list:
        """
        Parse and validate an FFmpeg command template.
        
        Args:
            command_template: Command template with {input}, {input1}, {output}, {font} placeholders.
            input_files: Dictionary mapping placeholder names to file paths.
            output_path: Path for the output file.
            font_path: Path to the bundled font file (for {font} placeholder).
            
        Returns:
            List of command arguments for subprocess.
            
        Raises:
            ValueError: If command is invalid or potentially dangerous.
        """
        # Check for dangerous patterns
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command_template):
                raise ValueError(f"Command contains potentially dangerous pattern: {pattern}")
        
        # Replace placeholders
        command = command_template
        
        # Replace output placeholder
        command = command.replace("{output}", output_path)
        
        # Replace font placeholder with proper escaping for FFmpeg filter syntax
        if font_path and "{font}" in command:
            # Use forward slashes (works on both Windows and Linux)
            escaped_font = font_path.replace("\\", "/")
            # Only escape colon if it's a Windows drive letter (e.g., C:)
            if len(escaped_font) >= 2 and escaped_font[1] == ":":
                escaped_font = escaped_font[0] + "\\:" + escaped_font[2:]
            command = command.replace("{font}", escaped_font)
        
        # Replace input placeholders
        for placeholder, file_path in input_files.items():
            command = command.replace(f"{{{placeholder}}}", file_path)
        
        # Check for unreplaced placeholders
        remaining_placeholders = re.findall(r"\{(\w+)\}", command)
        if remaining_placeholders:
            raise ValueError(f"Unreplaced placeholders in command: {remaining_placeholders}")
        
        # Parse into arguments - use posix=True for correct escaping in Linux/Docker
        try:
            args = shlex.split(command, posix=True)
            # posix=True automatically handles quote stripping and escapes
        except ValueError as e:
            raise ValueError(f"Invalid command syntax: {e}")
        
        # Validate arguments
        self._validate_args(args)
        
        return args
    
    def _validate_args(self, args: list) -> None:
        """
        Validate FFmpeg arguments for safety.
        
        Args:
            args: List of command arguments.
            
        Raises:
            ValueError: If any argument is potentially dangerous.
        """
        for i, arg in enumerate(args):
            # Check blocked arguments
            if arg in self.BLOCKED_ARGS:
                raise ValueError(f"Blocked argument: {arg}")
            
            # Check for attempts to escape via arguments
            for pattern in self.DANGEROUS_PATTERNS:
                if re.search(pattern, arg):
                    raise ValueError(f"Argument contains dangerous pattern: {arg}")
    
    async def execute(
        self, 
        args: list,
        output_path: str
    ) -> Tuple[bool, str, Optional[bytes]]:
        """
        Execute an FFmpeg command.
        
        Args:
            args: List of FFmpeg arguments (without 'ffmpeg' prefix).
            output_path: Expected output file path.
            
        Returns:
            Tuple of (success, message, output_content).
            output_content is the file bytes if successful, None otherwise.
        """
        # Build the full command
        cmd = ["ffmpeg", "-y"] + args  # -y to overwrite without asking
        
        try:
            # Run FFmpeg
            process = await asyncio.create_subprocess_exec(
                *cmd,
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
                
        except FileNotFoundError:
            return False, "FFmpeg not found. Please ensure FFmpeg is installed and in PATH.", None
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
