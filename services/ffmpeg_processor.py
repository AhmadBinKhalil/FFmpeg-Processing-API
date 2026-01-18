"""
FFmpeg processing service.
Handles command parsing, validation, and execution.
"""

import re
import asyncio
import shlex
from typing import Dict, Tuple, Optional, Union, List


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
        command_template: Union[str, List[str]], 
        input_files: Dict[str, str], 
        output_path: str,
        font_path: str = None
    ) -> Union[str, List[str]]:
        """
        Prepare the command by replacing placeholders.
        Supports both string (shell) and list (subprocess) templates.
        """
        # If list, process as direct arguments (No shell)
        if isinstance(command_template, list):
            return self._parse_command_list(command_template, input_files, output_path, font_path)
        
        # If string, process as shell command
        return self._parse_command_string(command_template, input_files, output_path, font_path)

    def _parse_command_list(self, template_list: List[str], input_files: Dict[str, str], output_path: str, font_path: str) -> List[str]:
        """Handle list-based argument parsing."""
        args = []
        for arg in template_list:
            # Simple placeholder replacement without quoting/escaping logic (arguments are raw)
            new_arg = arg
            new_arg = new_arg.replace("{output}", output_path)
            
            if font_path and "{font}" in new_arg:
                # For direct subprocess, verify if any FFmpeg-specific escaping is needed for the PATH
                # Usually forward slashes are safest for FFmpeg
                escaped_font = font_path.replace("\\", "/")
                # Windows drive letter escaping for filters might still be needed by FFmpeg itself?
                # But since we are bypassing shell, we pass valid path. 
                # FFmpeg filter parser handle paths differently. Let's stick to simple forward slashes.
                new_arg = new_arg.replace("{font}", escaped_font)
            
            for placeholder, file_path in input_files.items():
                new_arg = new_arg.replace(f"{{{placeholder}}}", file_path)
                
            args.append(new_arg)
            
        # Validate args
        self._validate_args(args)
        return args

    def _parse_command_string(self, command_template: str, input_files: Dict[str, str], output_path: str, font_path: str) -> str:
        """Handle string-based shell command parsing."""
        # Check for blocked arguments
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
            command = command.replace("{font}", quote_path(font_path))
        
        # Replace input placeholders
        for placeholder, file_path in input_files.items():
            command = command.replace(f"{{{placeholder}}}", quote_path(file_path))
        
        # Check for unreplaced placeholders
        remaining_placeholders = re.findall(r"\{(\w+)\}", command)
        if remaining_placeholders:
            raise ValueError(f"Unreplaced placeholders in command: {remaining_placeholders}")
            
        return command
    
    def _validate_args(self, args: list) -> None:
        """Validate list arguments."""
        for arg in args:
             for blocked in self.BLOCKED_ARGS:
                 if blocked in arg:
                     raise ValueError(f"Blocked argument: {blocked}")
    
    async def execute(
        self, 
        command: Union[str, List[str]],
        output_path: str
    ) -> Tuple[bool, str, Optional[bytes]]:
        """
        Execute an FFmpeg command.
        
        Args:
            command: Command string (shell execution) OR list of arguments (subprocess execution).
            output_path: Expected output file path.
        """
        if isinstance(command, list):
             return await self._execute_subprocess(command, output_path)
        else:
             return await self._execute_shell(command, output_path)

    async def _execute_subprocess(self, args: List[str], output_path: str) -> Tuple[bool, str, Optional[bytes]]:
        """Execute using asyncio.create_subprocess_exec (No Shell)."""
        cmd = ["ffmpeg", "-y"] + args
        print(f"DEBUG: Executing subprocess: {cmd}")
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            return await self._handle_process(process, output_path)
        except Exception as e:
            return False, f"Unexpected error during FFmpeg execution: {e}", None

    async def _execute_shell(self, command_str: str, output_path: str) -> Tuple[bool, str, Optional[bytes]]:
        """Execute using asyncio.create_subprocess_shell."""
        full_cmd = f"ffmpeg -y {command_str}"
        print(f"DEBUG: Executing shell command: {full_cmd}")
        
        try:
            process = await asyncio.create_subprocess_shell(
                full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            return await self._handle_process(process, output_path)
        except Exception as e:
            return False, f"Unexpected error during FFmpeg execution: {e}", None

    async def _handle_process(self, process, output_path):
        """Common process handling logic."""
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return False, f"FFmpeg command timed out after {self.timeout} seconds", None
        
        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")
            return False, f"FFmpeg error (exit code {process.returncode}): {error_msg}", None
        
        try:
            with open(output_path, "rb") as f:
                output_content = f.read()
            return True, "Processing completed successfully", output_content
        except FileNotFoundError:
            return False, "FFmpeg completed but output file was not created", None
        except Exception as e:
            return False, f"Error reading output file: {e}", None
    
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
