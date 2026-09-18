import uvicorn
from .config import CONFIG


def main() -> None:
    uvicorn.run(
        "wealth_monitor.app:app",
        host=CONFIG["web_host"],
        port=int(CONFIG["web_port"]),
        reload=False,
    )


if __name__ == "__main__":
    main()
