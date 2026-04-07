"""Script that uses mph without importing it."""
client = mph.start()
model = client.load("capacitor.mph")
