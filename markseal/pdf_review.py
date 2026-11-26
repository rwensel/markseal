from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import documents
from .boxset import BoxSet


@dataclass(frozen=True)
class PdfPageState:
    page: documents.PdfPage
    boxset: BoxSet
    confirmed: bool


class PdfReview:
    def __init__(self, path, *, document_factory=documents.PdfDocument):
        self.path = Path(path)
        self._document = document_factory(self.path)
        self._index = 0
        self._states = {}
        self._closed = False

    @property
    def page_index(self):
        return self._index

    @property
    def page_count(self):
        return self._document.page_count

    def open(self, index=0):
        return self._load(index)

    def switch(self, index, *, current, confirmed):
        if self._closed:
            raise documents.PdfError('This PDF is no longer open.')
        if not 0 <= index < self._document.page_count:
            raise documents.PdfError(
                f'Page {index + 1} does not exist in this PDF.')
        self._states[self._index] = (current, confirmed)
        return self._load(index)

    def unsaved(self):
        return any(boxset.boxes for boxset, _confirmed in self._states.values())

    def close(self):
        self._document.close()
        self._closed = True
        self._states.clear()
        self._index = 0

    def _load(self, index):
        if self._closed:
            raise documents.PdfError('This PDF is no longer open.')
        page = self._document.render_page(index)
        state = self._states.get(index)
        if state is None:
            state = (BoxSet(), False)
            self._states[index] = state
        self._index = index
        return PdfPageState(page, state[0], state[1])
