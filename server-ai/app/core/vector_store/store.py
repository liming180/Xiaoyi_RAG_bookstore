"""In-memory vector store seam for A1."""
class InMemoryVectorStore:
    def __init__(self): self.items = []
    def add(self, item): self.items.append(item)
    def all(self): return list(self.items)
