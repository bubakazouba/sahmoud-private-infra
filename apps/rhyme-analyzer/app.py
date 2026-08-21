"""Static wrapper for the Rhyme Analyzer, served behind the OAuth-gated proxy."""
import os
from pathlib import Path
from flask import Flask, send_from_directory

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
app = Flask(__name__)

@app.get("/")
def index():
    return send_from_directory(str(STATIC), "index.html")

@app.get("/healthz")
def healthz():
    return {"ok": True, "app": "rhyme-analyzer"}

@app.get("/<path:p>")
def static_files(p):
    return send_from_directory(str(STATIC), p)

if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", "18013"))
    app.run(host="127.0.0.1", port=port, debug=False)
