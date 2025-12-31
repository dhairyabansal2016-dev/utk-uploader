#!/usr/bin/env bash
# exit on error
set -o errexit

# Update and install ffmpeg
apt-get update && apt-get install -y ffmpeg

# Install python dependencies
pip install -r requirements.txt