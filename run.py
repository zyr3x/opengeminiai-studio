"""
Entry point for the OpenGeminiAI Studio Flask application.

This script initializes the Flask app using the application factory
and runs it. It's intended to be executed directly.
"""
from flask import Flask
from app import run

if __name__ == '__main__':
    run(Flask(__name__))


