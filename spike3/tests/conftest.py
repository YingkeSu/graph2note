import os, sys
SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SPIKE not in sys.path:
    sys.path.insert(0, SPIKE)
