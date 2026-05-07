from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Paths
    lens_db_path: Path = Path("/Users/stevenhoward/lens/data/lens.db")
    photo_watch_path: Path = Path("/Users/stevenhoward/Pictures/Incoming")
    boudoir_private_path: Path = Path("/Users/stevenhoward/lens/private/boudoir")
    portfolio_export_path: Path = Path("/Users/stevenhoward/lens/portfolio")

    # Ports
    lens_api_port: int = 8600
    lens_dashboard_port: int = 8800

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    vision_model: str = "qwen2.5vl:7b"
    text_model: str = "qwen2.5:14b"  # captions: 14b ~3x faster than 32b on M1 Max with marginal quality loss

    # Pipeline
    pipeline_workers: int = 3
    resize_max_dimension: int = 1024
    nima_threshold: float = 5.5
    blur_threshold: float = 100.0
    exposure_low: float = 0.05
    exposure_high: float = 0.95

    # Instagram
    instagram_access_token: str = ""
    instagram_account_id: str = ""
    public_image_base_url: str = ""  # Public HTTPS base URL for IG to fetch images (Cloudflare Tunnel)

    # Pixieset
    pixieset_api_key: str = ""
    pixieset_store_url: str = ""

    # Print pricing — Hudson Valley mid-range strategy
    # See ~/lens/PRICING.md for rationale and market comparisons
    # Format: size -> {paper, canvas, metal} dollars
    standard_prices: dict = {
        "8x10":  {"paper": 75,  "canvas": None, "metal": None},
        "11x14": {"paper": 110, "canvas": 200,  "metal": 225},
        "16x20": {"paper": 165, "canvas": 285,  "metal": 325},
        "20x30": {"paper": 260, "canvas": 420,  "metal": 475},
        "24x36": {"paper": 345, "canvas": 485,  "metal": 575},
    }
    fine_art_prices: dict = {
        "11x14": {"paper": 175,  "canvas": 300,  "metal": 350},
        "16x20": {"paper": 250,  "canvas": 400,  "metal": 475},
        "20x30": {"paper": 395,  "canvas": 575,  "metal": 675},
        "24x36": {"paper": 525,  "canvas": 750,  "metal": 875},
        "40x60": {"paper": 1100, "canvas": 1450, "metal": 1750},
    }
    # Default edition sizes by tier
    fine_art_edition_size: int = 25
    standard_edition_size: int = 0  # 0 = open edition

    # Scheduling
    instagram_morning_hour: int = 9
    instagram_evening_hour: int = 18
    scheduling_text_model: str = "qwen2.5:32b"
    scheduling_timeout_hours: int = 4

    # Business
    photographer_name: str = "Steven"
    business_name: str = ""
    location: str = "Hudson Valley, NY"
    genres: str = "wedding,portrait,boudoir,commercial,events,nature"

    @property
    def genre_list(self) -> list[str]:
        return [g.strip() for g in self.genres.split(",")]

    model_config = {"env_file": str(Path(__file__).parent.parent / ".env"), "extra": "ignore"}


settings = Settings()
