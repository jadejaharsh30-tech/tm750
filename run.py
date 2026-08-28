"""Start the API without invoking the unsigned uvicorn.exe shim."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)