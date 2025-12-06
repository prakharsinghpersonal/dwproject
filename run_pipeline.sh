#!/bin/bash

# Wrapper script to run pipeline with proper environment setup
# This ensures .env is loaded before running the Python script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ ERROR: .env file not found in $SCRIPT_DIR"
    echo "Please create a .env file with your Snowflake and Neo4j credentials."
    exit 1
fi

# Source .env file and export variables
echo "Loading environment variables from .env..."
set -a  # Automatically export all variables
source .env
set +a  # Stop automatically exporting

# Verify critical variables are set
if [ -z "$SNOWFLAKE_USER" ] || [ -z "$SNOWFLAKE_PASSWORD" ] || [ -z "$SNOWFLAKE_ACCOUNT" ]; then
    echo "❌ ERROR: Required Snowflake environment variables not set in .env"
    echo "Required variables: SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, SNOWFLAKE_ACCOUNT"
    echo ""
    echo "Current values:"
    echo "  SNOWFLAKE_USER: ${SNOWFLAKE_USER:-NOT SET}"
    echo "  SNOWFLAKE_ACCOUNT: ${SNOWFLAKE_ACCOUNT:-NOT SET}"
    exit 1
fi

# Run the Python pipeline with exported environment
echo "Starting pipeline execution..."
echo "Environment variables loaded: SNOWFLAKE_USER, SNOWFLAKE_ACCOUNT, SNOWFLAKE_WAREHOUSE, etc."
python run_pipeline.py

