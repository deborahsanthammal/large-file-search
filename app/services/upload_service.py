from pathlib import Path
from uuid import uuid4

from app.core.config import settings


class UploadService:
    def __init__(self) -> None:
        self.upload_directory = Path(settings.upload_directory)
        self.upload_directory.mkdir(parents=True, exist_ok=True)

    def create_upload(self, filename: str) -> tuple[str, Path]:
        upload_id = str(uuid4())

        file_path = self.upload_directory / f"{upload_id}.part"

        file_path.touch()

        return upload_id, file_path

    def finalize_upload(self, file_path: Path) -> Path:
        final_path = file_path.with_suffix("")
        file_path.replace(final_path)
        return final_path
    
    