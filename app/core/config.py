from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "Large File Processing & Semantic Search"
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    upload_directory: str = "./data/uploads"
    max_file_size: int = 10 * 1024 * 1024 * 1024  # 10 GB


settings = Settings()