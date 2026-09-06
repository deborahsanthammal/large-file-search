import argparse
import time
from pathlib import Path

import requests


BASE_URL = "http://127.0.0.1:8000"

MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1


def create_upload(file_path: Path) -> str:
    file_size = file_path.stat().st_size

    response = requests.post(
        f"{BASE_URL}/uploads",
        json={
            "filename": file_path.name,
            "size": file_size,
        },
    )

    response.raise_for_status()

    upload_id = response.json()["upload_id"]

    print(f"Created upload session: {upload_id}")

    return upload_id


def get_upload_status(upload_id: str) -> dict:
    response = requests.get(
        f"{BASE_URL}/uploads/{upload_id}",
    )

    response.raise_for_status()

    return response.json()


def upload_chunk(
    upload_id: str,
    chunk: bytes,
    offset: int,
) -> dict:
    response = requests.patch(
        f"{BASE_URL}/uploads/{upload_id}",
        headers={
            "Content-Length": str(len(chunk)),
            "Upload-Offset": str(offset),
        },
        data=chunk,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def upload_chunks(
    file_path: Path,
    upload_id: str,
    chunk_size: int,
    stop_after: int | None = None,
) -> None:
    status = get_upload_status(upload_id)

    offset = status["offset"]
    total_size = status["size"]

    print(f"Current server offset: {offset}")
    print(f"Total file size: {total_size}")

    if offset >= total_size:
        print("Upload is already complete.")
        return

    chunks_uploaded = 0

    with file_path.open("rb") as file:
        while offset < total_size:
            file.seek(offset)

            remaining = total_size - offset
            current_chunk_size = min(
                chunk_size,
                remaining,
            )

            chunk = file.read(current_chunk_size)

            if not chunk:
                raise RuntimeError(
                    "Unexpected end of local file."
                )

            retry_count = 0
            retry_delay = INITIAL_RETRY_DELAY

            while True:
                try:
                    result = upload_chunk(
                        upload_id=upload_id,
                        chunk=chunk,
                        offset=offset,
                    )

                    new_offset = result["offset"]

                    print(
                        f"Uploaded "
                        f"{new_offset}/{total_size} bytes"
                    )

                    offset = new_offset
                    chunks_uploaded += 1

                    break

                except requests.RequestException as exc:
                    retry_count += 1

                    if retry_count > MAX_RETRIES:
                        raise RuntimeError(
                            f"Upload failed after "
                            f"{MAX_RETRIES} retries: {exc}"
                        ) from exc

                    print(
                        f"Network error while uploading "
                        f"at offset {offset}."
                    )

                    print(
                        f"Retrying in "
                        f"{retry_delay} second(s)... "
                        f"({retry_count}/{MAX_RETRIES})"
                    )

                    time.sleep(retry_delay)

                    # The server may have received the
                    # chunk even if the response was lost.
                    # Always trust the server's offset.
                    status = get_upload_status(
                        upload_id
                    )

                    server_offset = status["offset"]

                    if server_offset != offset:
                        print(
                            f"Server offset is now "
                            f"{server_offset}. "
                            f"Continuing from there."
                        )

                        offset = server_offset
                        break

                    retry_delay *= 2

            if (
                stop_after is not None
                and chunks_uploaded >= stop_after
                and offset < total_size
            ):
                print()
                print(
                    "Upload intentionally stopped."
                )
                print(
                    f"Resume with upload ID: "
                    f"{upload_id}"
                )
                return

    print()
    print("Upload completed successfully.")
    print(f"Upload ID: {upload_id}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Upload files with resumable upload "
            "and automatic network retry support."
        )
    )

    parser.add_argument(
        "file",
        type=Path,
        help="Path to the file to upload.",
    )

    parser.add_argument(
        "--upload-id",
        help="Existing upload ID to resume.",
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1024 * 1024,
        help="Upload chunk size in bytes. Default: 1 MB.",
    )

    parser.add_argument(
        "--stop-after",
        type=int,
        help="Intentionally stop after this many chunks.",
    )

    args = parser.parse_args()

    file_path = args.file

    if not file_path.exists():
        raise SystemExit(
            f"File not found: {file_path}"
        )

    if not file_path.is_file():
        raise SystemExit(
            f"Not a file: {file_path}"
        )

    if args.chunk_size <= 0:
        raise SystemExit(
            "--chunk-size must be greater than 0."
        )

    if (
        args.stop_after is not None
        and args.stop_after <= 0
    ):
        raise SystemExit(
            "--stop-after must be greater than 0."
        )

    if args.upload_id:
        upload_id = args.upload_id

        status = get_upload_status(upload_id)

        if status["size"] != file_path.stat().st_size:
            raise SystemExit(
                "Local file size does not match "
                "the upload session size."
            )

        print(
            f"Resuming upload: {upload_id}"
        )

    else:
        upload_id = create_upload(file_path)

    upload_chunks(
        file_path=file_path,
        upload_id=upload_id,
        chunk_size=args.chunk_size,
        stop_after=args.stop_after,
    )


if __name__ == "__main__":
    main()