from unittest.mock import MagicMock

class Parent(MagicMock):
    pass

class Child(Parent):
    def __init__(self):
        print("Child init called")
        super().__init__()

print("Instantiating Child...")
c = Child()
print("Child instantiated")
