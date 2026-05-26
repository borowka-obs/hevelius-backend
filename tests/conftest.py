"""
Pytest configuration shared by all tests.
"""

import warnings

from marshmallow import warnings as marshmallow_warnings

# Marshmallow 4 migration notices from dependencies and legacy field options.
warnings.filterwarnings("ignore", category=marshmallow_warnings.RemovedInMarshmallow4Warning)
