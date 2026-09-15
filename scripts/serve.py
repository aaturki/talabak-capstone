from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if __name__ == "__main__":
    import uvicorn
    from talabak.api import create_app
    root = Path(__file__).resolve().parents[1]
    (root / "runtime").mkdir(exist_ok=True)
    uvicorn.run(create_app(root / "runtime/store.sqlite"), host="127.0.0.1", port=8765, access_log=False)
