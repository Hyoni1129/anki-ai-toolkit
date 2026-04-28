from unittest.mock import MagicMock

# This mimics sys.modules['aqt.qt'] = MagicMock()
# and then doing from aqt.qt import QDialog
mock_qt = MagicMock()
QDialog = mock_qt.QDialog 

print(f"Type of QDialog: {type(QDialog)}")

try:
    class MyDialog(QDialog):
        def __init__(self):
            print("MyDialog init")
            super().__init__()
            
    print("Class definition succeeded")
    d = MyDialog()
    print("Instantiation succeeded")

except TypeError as e:
    print(f"TypeError: {e}")
except Exception as e:
    print(f"Error: {e}")
