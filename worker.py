#!/usr/bin/env python3
"""
Wrapper script for bulk_email_sender.worker.
Legacy entry point for Tauri desktop app.
"""

from bulk_email_sender.worker import main

if __name__ == "__main__":
    main()
