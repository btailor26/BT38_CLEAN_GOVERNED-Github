from app import app
from sync_service import start_sync_service
import threading

if __name__ == '__main__':
    # Start the background sync service
    sync_thread = threading.Thread(target=start_sync_service, daemon=True)
    sync_thread.start()
    
    # Start the Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)
