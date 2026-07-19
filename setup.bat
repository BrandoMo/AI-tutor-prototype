@echo off
echo Setting up AI Tutor prototype...

python -m venv venv
call venv\Scripts\activate

pip install -r requirements.txt

echo.
echo Setup complete. To run the server:
echo   venv\Scripts\activate
echo   uvicorn app.main:app --reload
echo.
echo Then open http://127.0.0.1:8000 in your browser.
pause
