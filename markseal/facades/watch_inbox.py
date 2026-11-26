from __future__ import annotations

from .. import watches as watch_store

POLICY_LABELS = {'manual': 'MANUAL', 'automatic': 'AUTO'}


class WatchInbox:
    def __init__(self, owner):
        self.owner = owner

    def counts_for(self, watch):
        folder_key = watch_store.key(watch.path)
        result = self.owner._counts.get(folder_key)
        if result is None:
            result = self.owner.records.counts_for(watch)
        return result

    def refresh(self, watch):
        self.owner._counts[watch_store.key(watch.path)] = (
            self.owner.records.counts_for(watch))

    def refresh_all(self):
        for folder in self.owner.store.folders:
            self.refresh(folder)

    def rows(self):
        rows = []
        for folder in self.owner.store.folders:
            folder_key = watch_store.key(folder.path)
            result = self.counts_for(folder)
            rows.append({
                'path': str(folder.path),
                'name': folder.path.name,
                'policy': POLICY_LABELS[folder.policy],
                'new': result.new,
                'queued': result.queued,
                'existing': result.existing,
                'needs_review': result.needs_review,
                'exported': result.exported,
                'recursive': folder.recursive,
                'output': str(folder.export_directory),
                'issues': [{'name': name, 'detail': detail}
                           for name, detail in result.issues],
                'error': self.owner._errors.get(folder_key, ''),
            })
        return rows
