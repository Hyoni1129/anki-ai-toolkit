# -*- coding: utf-8 -*-
"""
Stella Anki Tools - Unified Anki Add-on

Combines three powerful features into a single add-on:
1. AI Translation - Context-aware vocabulary translation using Gemini AI
2. AI Image Generation - Visual flashcard images using Gemini Imagen
3. AI Sentence Generation - Example sentences for vocabulary learning

Copyright (c) 2026 JeongHan Lee
License: CC BY-NC-SA 4.0

Usage:
    This add-on is automatically initialized when Anki starts.
    Access features via Tools menu or editor buttons.
"""

__version__ = "1.0.0"
__author__ = "Stella Anki Team"


if __name__ != "__main__":
    try:
        # Add lib path first to ensure bundled dependencies are available
        import sys
        import os
        
        addon_dir = os.path.dirname(__file__)
        lib_path = os.path.join(addon_dir, "lib")
        
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)
        
        # Handle google namespace package issues - CRITICAL for bundled libraries
        # Must prioritize our bundled version over any system-installed packages
        google_lib_path = os.path.join(lib_path, "google")
        if "google" in sys.modules:
            import google
            if hasattr(google, "__path__"):
                if google_lib_path not in google.__path__:
                    # Insert at beginning to prioritize bundled version
                    google.__path__.insert(0, google_lib_path)
        
        from aqt import mw
        
        if mw:
            # Initialize configuration
            from .config.settings import ConfigManager
            config_manager = ConfigManager()
            config_manager.initialize(addon_dir)
            
            # Initialize logger
            from .core.logger import get_logger
            logger = get_logger("main")
            logger.info(f"Stella Anki Tools v{__version__} initializing...")
            
            # Initialize API key manager
            from .core.api_key_manager import APIKeyManager
            key_manager = APIKeyManager(addon_dir)
            
            # Check for API keys
            if not key_manager.get_current_key():
                # Try to load from legacy config
                try:
                    addon_name = __name__.split('.')[0]
                    legacy_config = mw.addonManager.getConfig(addon_name)
                    if legacy_config and legacy_config.get("gemini_api_key"):
                        key_manager.add_key(legacy_config["gemini_api_key"])
                        logger.info("Migrated legacy API key")
                except Exception:
                    pass
            
            # Initialize main controller with menu
            from .ui.main_controller import initialize as init_controller
            controller = init_controller(mw)
            mw.stella_anki_tools = controller
            
            # Initialize editor integration
            from .ui.editor_integration import setup_editor_integration
            editor_integration = setup_editor_integration()
            mw.stella_editor = editor_integration
            
            logger.info("Stella Anki Tools initialized successfully")
            
    except Exception as e:
        # Notify user on initialization failure
        import traceback
        error_details = traceback.format_exc()
        
        try:
            from aqt.utils import showInfo
            showInfo(
                f"Error initializing Stella Anki Tools:\n{str(e)}\n\n"
                "Please try disabling and re-enabling the add-on in Tools > Add-ons."
            )
        except Exception:
            pass
        
        # Use stderr for initialization failures (logger may not be available)
        import sys
        sys.stderr.write(f"Stella Anki Tools initialization failed: {e}\n")
        sys.stderr.write(f"{error_details}\n")

else:
    # Use stderr for direct execution warning
    import sys
    sys.stderr.write("This file is an Anki add-on. Please run it within Anki.\n")
