import socket
import time
import os
import sys

def main():
    use_mysql = os.environ.get('USE_MYSQL', 'False').lower() in ('true', '1', 'yes')
    if not use_mysql:
        print("Using SQLite - skipping external database socket check.")
        sys.exit(0)

    host = os.environ.get('DB_HOST', 'db')
    port = int(os.environ.get('DB_PORT', 3306))
    print(f"Waiting for MySQL database connection on {host}:{port}...")
    
    for i in range(30):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect((host, port))
            s.close()
            print("Database connection established successfully!")
            sys.exit(0)
        except Exception as e:
            print(f"Database not ready yet (attempt {i+1}/30): {e}")
            time.sleep(2)
            
    print("Error: Database connection timed out after 60 seconds.")
    sys.exit(1)

if __name__ == '__main__':
    main()
