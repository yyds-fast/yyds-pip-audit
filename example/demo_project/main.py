# -*- coding:utf-8 -*-
import os
import sys
import cv2
import requests
import yaml
from google.cloud import storage

from utils import calculate_something

def main():
    print("Demo project starting...")
    print(f"OS name: {os.name}")
    print(f"Calculation: {calculate_something(16)}")
    # Mocking usage of imports to prevent unused module warnings (if any linters complain)
    print(f"cv2 version: {getattr(cv2, '__version__', 'unknown')}")
    print(f"requests: {requests.__name__}")
    print(f"yaml: {yaml.__name__}")

if __name__ == "__main__":
    main()
