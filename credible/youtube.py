"""Private-first uploads with recovery by a durable slot marker."""
from __future__ import annotations

from .core import now, parse


class YouTube:
    def __init__(self):
        import upload
        self.api = upload._service()

    def find(self, marker):
        channel = self.api.channels().list(part='contentDetails', mine=True).execute()['items'][0]
        playlist = channel['contentDetails']['relatedPlaylists']['uploads']
        page = None
        # Include private uploads and paginate; never interpret a failed lookup as no match.
        while True:
            response = self.api.playlistItems().list(part='contentDetails', playlistId=playlist,
                maxResults=50, **({'pageToken': page} if page else {})).execute()
            ids = [r['contentDetails']['videoId'] for r in response.get('items', [])]
            if ids:
                videos = self.api.videos().list(part='snippet,status', id=','.join(ids)).execute()
                for item in videos.get('items', []):
                    if marker in item['snippet'].get('tags', []):
                        return item
            page = response.get('nextPageToken')
            if not page:
                return None

    def upload_private(self, path, episode, marker):
        from googleapiclient.http import MediaFileUpload
        sources = '\n'.join(dict.fromkeys(e['source_url'] for e in episode['evidence']))
        description = (episode['claim'] + '\n\nIllustrations explain the mechanism; example values are not measurements.'
                       '\n\nSources:\n' + sources + '\n\nHidden Logic: everyday things, explained clearly.\n#shorts')
        request = self.api.videos().insert(part='snippet,status', body={
            'snippet': {'title': episode['title'], 'description': description,
                'tags': ['Hidden Logic', episode['pillar'], marker], 'categoryId': '27',
                'defaultLanguage': 'en'},
            'status': {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False}},
            media_body=MediaFileUpload(str(path), chunksize=8*1024*1024, resumable=True))
        response = None
        while response is None:
            _, response = request.next_chunk(num_retries=3)
        return response['id']

    def schedule(self, video_id, publish_at):
        if parse(publish_at) <= now():
            raise ValueError('Missed slot; leave upload private for explicit recovery')
        return self.api.videos().update(part='status', body={'id': video_id,
            'status': {'privacyStatus': 'private', 'publishAt': publish_at,
                       'selfDeclaredMadeForKids': False}}).execute()


def deliver(slot, episode, folder, backend, persist):
    marker = 'hl-slot-' + slot['id']
    if slot.get('status') == 'scheduled':
        return slot
    if not slot.get('video_id'):
        found = backend.find(marker)
        if found:
            slot['video_id'] = found['id']
            slot['status'] = 'uploaded'
            persist()
        elif slot.get('status') in ('uploading', 'upload_uncertain'):
            # YouTube can be eventually consistent. Never blindly repeat an insert.
            slot['status'] = 'upload_uncertain'
            persist()
            raise RuntimeError('Upload outcome uncertain; reconciliation required before another insert')
        else:
            slot['status'] = 'uploading'
            persist()
            try:
                slot['video_id'] = backend.upload_private(folder / 'short.mp4', episode, marker)
            except Exception:
                slot['status'] = 'upload_uncertain'
                persist()
                raise
            slot['status'] = 'uploaded'
            persist()
    backend.schedule(slot['video_id'], slot['publish_at'])
    slot['status'] = 'scheduled'
    persist()
    return slot
