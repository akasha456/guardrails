#!/bin/bash

# Function to handle script exit
cleanup() {
    echo "Stopping all services..."
    # Add commands to kill processes if needed, but since we are opening new terminals, 
    # closing the main script won't necessarily kill them unless we track PIDs.
    # For now, we rely on the user closing the terminals.
}

# Trap script exit
trap cleanup EXIT

echo "Starting deployment..."

# Check if gnome-terminal is available
if command -v gnome-terminal &> /dev/null; then
    echo "Using gnome-terminal"
    
    # Start Model Server
    gnome-terminal --tab --title="Model Server" -- bash -c "echo 'Starting Model Server...'; ./venv/bin/python3 modelserv.py; exec bash"
    
    # Wait a bit for model server to initialize
    sleep 2
    
    # Start Guard Server
    gnome-terminal --tab --title="Guard Server" -- bash -c "echo 'Starting Guard Server...'; ./venv/bin/python3 guardserver.py; exec bash"
    
    # Wait a bit for guard server
    sleep 2
    
    # Start Frontend
    gnome-terminal --tab --title="Frontend" -- bash -c "echo 'Starting Frontend...'; ./venv/bin/python3 -m streamlit run main.py; exec bash"

else
    echo "gnome-terminal not found. Trying xterm..."
    
    if command -v xterm &> /dev/null; then
        xterm -T "Model Server" -e "./venv/bin/python3 modelserv.py" &
        sleep 2
        xterm -T "Guard Server" -e "./venv/bin/python3 guardserver.py" &
        sleep 2
        xterm -T "Frontend" -e "./venv/bin/python3 -m streamlit run main.py" &
    else
        echo "Error: No suitable terminal emulator found (checked gnome-terminal and xterm)."
        echo "Please install gnome-terminal or xterm, or run the services manually."
        exit 1
    fi
fi

echo "All services launch commands issued."
