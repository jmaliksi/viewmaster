# ViewMaster

## Setup

1. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application**:
   
   For development using FastAPI's dev command:
   ```bash
   fastapi dev main.py
   ```

   Or using uvicorn directly:
   ```bash
   uvicorn main:app --reload
   ```

   Or use the main.py file:
   ```bash
   python main.py
   ```

## Project Structure

```
viewmaster/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI app initialization
│   └── routers/
│       ├── __init__.py
│       └── api.py        # API routes (ready for your endpoints)
├── main.py               # Entry point
├── requirements.txt      # Dependencies
└── README.md            # This file
```

## Development

For development with auto-reload using FastAPI's dev command:
```bash
fastapi dev main.py
```

This will automatically:
- Enable auto-reload on code changes
- Start the server on `http://localhost:8000`
- Provide access to interactive API docs at `/docs`

Alternatively, using uvicorn directl
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```