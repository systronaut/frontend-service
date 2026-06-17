# Author: Systronaut
# WSGI entrypoint. `gunicorn wsgi:app` in the container; `python wsgi.py` in dev.

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
