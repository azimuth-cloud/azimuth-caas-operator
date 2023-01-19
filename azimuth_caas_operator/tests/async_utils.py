class AsyncIterList:
    def __init__(self, items):
        self.items = items
        self.kwargs = None

    async def list(self, **kwargs):
        self.kwargs = kwargs
        for item in self.items:
            yield item
