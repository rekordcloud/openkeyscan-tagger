#!/usr/bin/env python3
"""
Key Tagging Server - stdin/stdout JSON Protocol

Runs as a long-running process, writing and reading key metadata to/from audio files.
Communicates via line-delimited JSON (NDJSON) protocol.

Protocol:
  Write Request:  {"id": "uuid", "path": "/absolute/path/file.mp3", "key": "9A"}
  Read Request:    {"id": "uuid", "path": "/absolute/path/file.mp3"}
  Success:         {"id": "uuid", "status": "success", "key": "9A", "filename": "file.mp3", "format": "mp3", "albumArtPath": "/tmp/openkeyscan-art-uuid.jpg"}
  Error:           {"id": "uuid", "status": "error", "error": "Error message", "filename": "file.mp3"}
  Ready:           {"type": "ready"}
  Heartbeat:       {"type": "heartbeat"}

Note: albumArtPath is optional and only included if album art is found in the file.

Note: If "key" field is missing or empty, the request is treated as a read operation.
"""

import sys
import os
import json
import threading
import time
import tempfile
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Import mutagen for audio tagging
from mutagen import File
from mutagen.id3 import ID3, TKEY, APIC, ID3NoHeaderError
from mutagen.mp4 import MP4
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.aiff import AIFF
from mutagen.wave import WAVE

# ============================================================================
# CRITICAL: UTF-8 Encoding Configuration for Windows/PyInstaller
# ============================================================================
# On Windows, Python defaults to cp1252 encoding for stdio, but Node.js
# child_process sends UTF-8. This mismatch causes UnicodeDecodeError when
# reading JSON with non-ASCII characters (e.g., file paths with accents).
#
# Solution: Reconfigure stdin/stdout to UTF-8 at runtime at MODULE LEVEL.
# Must be done BEFORE any sys.stdin.readline() calls and at module level
# (not inside a function) so it executes during import.
# ============================================================================
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and PyInstaller."""
    try:
        base_path = Path(sys._MEIPASS)
    except AttributeError:
        base_path = Path(__file__).parent
    return base_path / relative_path


def sync_file(file_path):
    """Force file to be written to disk."""
    try:
        # Open and sync the file to ensure it's written
        fd = os.open(file_path, os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
    except Exception:
        pass  # Best effort, don't fail if sync doesn't work


def get_vorbis_field_case_insensitive(audio, field_name):
    """
    Get a Vorbis comment field value with case-insensitive lookup.

    Args:
        audio: Mutagen audio object with Vorbis comments
        field_name: Field name to search for (case-insensitive)

    Returns:
        Field value if found, None otherwise
    """
    field_lower = field_name.lower()
    for key in audio.keys():
        if key.lower() == field_lower:
            value_list = audio[key]
            return value_list[0] if value_list else None
    return None


def get_mp4_field_case_insensitive(audio, field_name):
    """
    Get an MP4 freeform tag value with case-insensitive lookup.

    Args:
        audio: Mutagen MP4 audio object
        field_name: Field name to search for (case-insensitive)

    Returns:
        Field value if found, None otherwise
    """
    field_lower = field_name.lower()
    for key in audio.keys():
        if key.lower() == field_lower:
            value_list = audio[key]
            if value_list:
                value = value_list[0]
                return value.decode('utf-8') if isinstance(value, bytes) else str(value)
    return None


def extract_album_art(file_path):
    """
    Extract album art from an audio file and save to a temporary file.

    Args:
        file_path (Path): Path to audio file

    Returns:
        str or None: Path to temporary file containing album art, or None if not found
    """
    try:
        file_ext = file_path.suffix.lower()
        image_data = None
        mime_type = None

        # MP3 files - read APIC frame
        if file_ext in ['.mp3', '.aac']:
            try:
                audio = ID3(file_path)
                # Get first picture frame (usually front cover)
                for tag in audio.values():
                    if isinstance(tag, APIC):
                        image_data = tag.data
                        mime_type = tag.mime
                        break
            except ID3NoHeaderError:
                pass

        # MP4/M4A/ALAC files - read covr atom
        elif file_ext in ['.mp4', '.m4a', '.alac']:
            audio = MP4(file_path)
            if 'covr' in audio and len(audio['covr']) > 0:
                cover = audio['covr'][0]
                image_data = bytes(cover)
                # MP4 covers are typically JPEG or PNG
                # Try to detect type from magic bytes
                if image_data[:4] == b'\xff\xd8\xff\xe0' or image_data[:2] == b'\xff\xd8':
                    mime_type = 'image/jpeg'
                elif image_data[:8] == b'\x89PNG\r\n\x1a\n':
                    mime_type = 'image/png'
                else:
                    mime_type = 'image/jpeg'  # Default to JPEG

        # FLAC files - read Picture block
        elif file_ext == '.flac':
            audio = FLAC(file_path)
            if audio.pictures and len(audio.pictures) > 0:
                picture = audio.pictures[0]
                image_data = picture.data
                mime_type = picture.mime

        # OGG Vorbis files - read embedded pictures (Vorbis comments)
        elif file_ext == '.ogg':
            audio = OggVorbis(file_path)
            # OGG can have METADATA_BLOCK_PICTURE in Vorbis comments
            # This is base64-encoded FLAC picture block
            if 'metadata_block_picture' in audio:
                import base64
                picture_data = base64.b64decode(audio['metadata_block_picture'][0])
                # Parse FLAC picture block
                # Skip the picture type (4 bytes) and mime length (4 bytes)
                mime_len = int.from_bytes(picture_data[4:8], 'big')
                mime_type = picture_data[8:8+mime_len].decode('ascii')
                # Skip description and other metadata to get to image data
                # This is complex, so we'll use mutagen's built-in parsing
                from mutagen.flac import Picture
                picture = Picture(picture_data)
                image_data = picture.data
                mime_type = picture.mime

        # AIFF/AIF files - read ID3 tags with APIC
        elif file_ext in ['.aiff', '.aif']:
            audio = AIFF(file_path)
            if audio.tags:
                for tag in audio.tags.values():
                    if isinstance(tag, APIC):
                        image_data = tag.data
                        mime_type = tag.mime
                        break

        # WAV files - read ID3 tags with APIC
        elif file_ext == '.wav':
            audio = WAVE(file_path)
            if audio.tags:
                for tag in audio.tags.values():
                    if isinstance(tag, APIC):
                        image_data = tag.data
                        mime_type = tag.mime
                        break

        # If we found image data, write to temp file
        if image_data:
            # Determine file extension from MIME type
            if mime_type == 'image/png':
                ext = '.png'
            elif mime_type in ['image/jpeg', 'image/jpg']:
                ext = '.jpg'
            else:
                ext = '.jpg'  # Default to JPEG

            # Create temp file with unique name
            temp_id = str(uuid.uuid4())
            temp_path = os.path.join(tempfile.gettempdir(), f'openkeyscan-art-{temp_id}{ext}')

            # Write image data
            with open(temp_path, 'wb') as f:
                f.write(image_data)

            return temp_path

        return None

    except Exception as e:
        # Album art extraction is optional, don't fail the whole request
        print(f"Warning: Failed to extract album art: {e}", file=sys.stderr)
        return None


def read_key_from_file(file_path):
    """
    Read key metadata from an audio file using mutagen.

    For maximum compatibility, checks both standard and legacy field names:
    - FLAC/OGG: Prefers 'initialkey' over 'KEY' (case-insensitive)
    - MP4/M4A: Prefers '----:com.apple.iTunes:initialkey' over '----:com.apple.iTunes:KEY' (case-insensitive)
    - ID3 formats: Reads 'TKEY' frame

    Field name matching is case-insensitive to handle variations like:
    'initialkey', 'INITIALKEY', 'InitialKey', 'KEY', 'key', etc.

    Args:
        file_path (Path): Path to audio file

    Returns:
        tuple: (success: bool, key_value: str or None, format: str, error_message: str or None)
    """
    try:
        file_ext = file_path.suffix.lower()

        # MP3 files - read ID3v2 TKEY frame
        if file_ext == '.mp3':
            try:
                audio = ID3(file_path)
                if 'TKEY' in audio:
                    key_value = str(audio['TKEY'].text[0]) if audio['TKEY'].text else None
                    return True, key_value, 'mp3', None
                return True, None, 'mp3', None
            except ID3NoHeaderError:
                return True, None, 'mp3', None

        # AAC files with ID3 tags (ADTS AAC)
        elif file_ext == '.aac':
            try:
                audio = ID3(file_path)
                if 'TKEY' in audio:
                    key_value = str(audio['TKEY'].text[0]) if audio['TKEY'].text else None
                    return True, key_value, 'aac', None
                return True, None, 'aac', None
            except ID3NoHeaderError:
                return True, None, 'aac', None

        # MP4/M4A/ALAC files - read freeform tags
        elif file_ext in ['.mp4', '.m4a', '.alac']:
            audio = MP4(file_path)
            # Check initialkey first (standard), then KEY (legacy) - case insensitive
            key_value = get_mp4_field_case_insensitive(audio, '----:com.apple.iTunes:initialkey')
            if not key_value:
                key_value = get_mp4_field_case_insensitive(audio, '----:com.apple.iTunes:KEY')
            return True, key_value, file_ext[1:], None

        # FLAC files - read Vorbis comments
        elif file_ext == '.flac':
            audio = FLAC(file_path)
            # Check initialkey first (standard), then KEY (legacy) - case insensitive
            key_value = get_vorbis_field_case_insensitive(audio, 'initialkey')
            if not key_value:
                key_value = get_vorbis_field_case_insensitive(audio, 'KEY')
            return True, key_value, 'flac', None

        # OGG Vorbis files - read Vorbis comments
        elif file_ext == '.ogg':
            audio = OggVorbis(file_path)
            # Check initialkey first (standard), then KEY (legacy) - case insensitive
            key_value = get_vorbis_field_case_insensitive(audio, 'initialkey')
            if not key_value:
                key_value = get_vorbis_field_case_insensitive(audio, 'KEY')
            return True, key_value, 'ogg', None

        # AIFF/AIF files - read ID3 tags
        elif file_ext in ['.aiff', '.aif']:
            audio = AIFF(file_path)
            if audio.tags and 'TKEY' in audio.tags:
                key_value = str(audio.tags['TKEY'].text[0]) if audio.tags['TKEY'].text else None
                return True, key_value, file_ext[1:], None
            return True, None, file_ext[1:], None

        # WAV files - read ID3 tags
        elif file_ext == '.wav':
            audio = WAVE(file_path)
            if audio.tags and 'TKEY' in audio.tags:
                key_value = str(audio.tags['TKEY'].text[0]) if audio.tags['TKEY'].text else None
                return True, key_value, 'wav', None
            return True, None, 'wav', None

        else:
            return False, None, None, f"Unsupported file format: {file_ext}"

    except Exception as e:
        return False, None, None, str(e)


def write_key_to_file(file_path, key_value):
    """
    Write key metadata to an audio file using mutagen.

    Args:
        file_path (Path): Path to audio file
        key_value (str): Key value to write (e.g., "9A", "E minor", "2m")

    Returns:
        tuple: (success: bool, error_message: str or None, format: str)
    """
    try:
        file_ext = file_path.suffix.lower()

        # MP3 files - use ID3v2.4 TKEY frame
        if file_ext == '.mp3':
            try:
                audio = ID3(file_path)
            except ID3NoHeaderError:
                # Create new ID3 tag if none exists
                audio = ID3()

            # Delete existing TKEY frame and add new one
            audio.delall('TKEY')
            audio.add(TKEY(encoding=3, text=key_value))
            audio.save(file_path, v2_version=4)
            sync_file(file_path)
            return True, None, 'mp3'

        # AAC files with ID3 tags (ADTS AAC)
        elif file_ext == '.aac':
            try:
                audio = ID3(file_path)
            except ID3NoHeaderError:
                # Create new ID3 tag if none exists
                audio = ID3()

            # Delete existing TKEY frame and add new one
            audio.delall('TKEY')
            audio.add(TKEY(encoding=3, text=key_value))
            audio.save(file_path, v2_version=4)
            sync_file(file_path)
            return True, None, 'aac'

        # MP4/M4A/ALAC files - use freeform tags
        # Write to both 'initialkey' (standard) and 'KEY' (legacy) for compatibility
        elif file_ext in ['.mp4', '.m4a', '.alac']:
            audio = MP4(file_path)
            audio['----:com.apple.iTunes:initialkey'] = key_value.encode('utf-8')
            audio['----:com.apple.iTunes:KEY'] = key_value.encode('utf-8')
            audio.save()
            sync_file(file_path)
            return True, None, file_ext[1:]

        # FLAC files - use Vorbis comments
        # Write to both 'initialkey' (standard) and 'KEY' (legacy) for compatibility
        elif file_ext == '.flac':
            audio = FLAC(file_path)
            audio['initialkey'] = key_value
            audio['KEY'] = key_value
            audio.save()
            sync_file(file_path)
            return True, None, 'flac'

        # OGG Vorbis files - use Vorbis comments
        # Write to both 'initialkey' (standard) and 'KEY' (legacy) for compatibility
        elif file_ext == '.ogg':
            audio = OggVorbis(file_path)
            audio['initialkey'] = key_value
            audio['KEY'] = key_value
            audio.save()
            sync_file(file_path)
            return True, None, 'ogg'

        # AIFF/AIF files - use ID3 tags
        elif file_ext in ['.aiff', '.aif']:
            audio = AIFF(file_path)
            if audio.tags is None:
                audio.add_tags()
            # Delete existing TKEY frame and add new one
            audio.tags.delall('TKEY')
            audio.tags.add(TKEY(encoding=3, text=key_value))
            audio.save()
            sync_file(file_path)
            return True, None, file_ext[1:]

        # WAV files - use ID3 tags
        elif file_ext == '.wav':
            audio = WAVE(file_path)
            if audio.tags is None:
                audio.add_tags()
            # Delete existing TKEY frame and add new one
            audio.tags.delall('TKEY')
            audio.tags.add(TKEY(encoding=3, text=key_value))
            audio.save()
            sync_file(file_path)
            return True, None, 'wav'

        else:
            return False, f"Unsupported file format: {file_ext}", None

    except Exception as e:
        return False, str(e), None


class KeyTaggingServer:
    """
    Server that processes key tagging requests via stdin/stdout.

    Uses thread pool for concurrent processing.
    """

    def __init__(self, num_workers=4):
        """
        Initialize the server.

        Args:
            num_workers (int): Number of worker threads (default: 4)
        """
        self.num_workers = num_workers
        self.executor = ThreadPoolExecutor(max_workers=num_workers)

        # Log configuration
        print(f"Server configuration:", file=sys.stderr)
        print(f"  Workers: {self.num_workers}", file=sys.stderr)

        self.running = True

    def send_message(self, message):
        """Send a JSON message to stdout."""
        try:
            json_str = json.dumps(message)
            print(json_str, flush=True)
        except Exception as e:
            print(f"Error sending message: {e}", file=sys.stderr)

    def process_request(self, request):
        """
        Process a single key tagging or reading request.

        Args:
            request (dict): Request with 'id', 'path', and optionally 'key' fields
                - If 'key' is provided: writes key to file
                - If 'key' is missing/empty: reads key from file

        Returns:
            dict: Response message
        """
        request_id = request.get('id', 'unknown')
        file_path = request.get('path', '')
        key_value = request.get('key', '')

        try:
            audio_path = Path(file_path)

            if not audio_path.exists():
                return {
                    'id': request_id,
                    'status': 'error',
                    'error': 'File not found',
                    'filename': audio_path.name
                }

            # If no key provided, treat as read request
            if not key_value or key_value == '':
                success, read_key, format_type, error_msg = read_key_from_file(audio_path)

                if success:
                    # Extract album art if present
                    album_art_path = extract_album_art(audio_path)

                    response = {
                        'id': request_id,
                        'status': 'success',
                        'key': read_key,
                        'filename': audio_path.name,
                        'format': format_type
                    }

                    # Add album art path if extracted
                    if album_art_path:
                        response['albumArtPath'] = album_art_path

                    return response
                else:
                    return {
                        'id': request_id,
                        'status': 'error',
                        'error': error_msg or 'Failed to read key',
                        'filename': audio_path.name
                    }

            # Write key to file
            success, error_msg, format_type = write_key_to_file(audio_path, key_value)

            if success:
                return {
                    'id': request_id,
                    'status': 'success',
                    'key': key_value,
                    'filename': audio_path.name,
                    'format': format_type
                }
            else:
                return {
                    'id': request_id,
                    'status': 'error',
                    'error': error_msg,
                    'filename': audio_path.name
                }

        except Exception as e:
            return {
                'id': request_id,
                'status': 'error',
                'error': str(e),
                'filename': Path(file_path).name if file_path else 'unknown'
            }

    def handle_request(self, line):
        """Parse and handle a request line."""
        try:
            request = json.loads(line)

            # Process the request
            response = self.process_request(request)
            self.send_message(response)

        except json.JSONDecodeError as e:
            print(f"Invalid JSON: {e}", file=sys.stderr)
        except Exception as e:
            print(f"Error handling request: {e}", file=sys.stderr)

    def run(self):
        """Main server loop - read from stdin and process requests."""
        # Send ready message
        self.send_message({'type': 'ready'})
        print("Server ready, waiting for requests...", file=sys.stderr)

        # Start heartbeat thread
        def heartbeat():
            while self.running:
                time.sleep(30)
                if self.running:
                    self.send_message({'type': 'heartbeat'})

        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()

        # Process requests from stdin
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue

                # Submit to thread pool for concurrent processing
                self.executor.submit(self.handle_request, line)

        except KeyboardInterrupt:
            print("Shutting down...", file=sys.stderr)
        finally:
            self.running = False
            self.executor.shutdown(wait=True)
            print("Server stopped", file=sys.stderr)


def main():
    """Entry point for the server."""
    import argparse

    parser = argparse.ArgumentParser(description="Key Tagging Server (stdin/stdout JSON protocol)")
    parser.add_argument('-w', '--workers', type=int, default=4,
                        help="Number of worker threads (default: 4)")

    args = parser.parse_args()

    server = KeyTaggingServer(num_workers=args.workers)
    server.run()


if __name__ == '__main__':
    main()
