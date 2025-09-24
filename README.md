Agri Backend MVP v2 - Quickstart

Run:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

Place your full dataset at data/crop_data.xlsx if you have a larger file.
