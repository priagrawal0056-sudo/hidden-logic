"""Bounded discovery from reviewed publisher pages, with same-host HTTPS links only."""
import datetime as dt
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from .core import now, read, save
from .evidence import retrieve


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(v for k,v in attrs if k == 'href' and v)


def discover(catalog, cache, state_path, limit=6):
    import requests
    state = read(state_path, {'seen': [], 'cursor': 0, 'sources': []})
    known = set(state['seen']) | {s['url'] for s in catalog}
    sources = list(state['sources'])
    for i in range(min(3,len(catalog))):
        parent = catalog[(state['cursor']+i) % len(catalog)]
        try:
            response = requests.get(parent['url'], timeout=15)
            response.raise_for_status()
            parser = Links(); parser.feed(response.text)
            for link in parser.links:
                url = urlsplit(urljoin(parent['url'],link))
                if (url.scheme != 'https' or url.netloc != urlsplit(parent['url']).netloc
                        or url.query or any(x in url.path.lower() for x in
                        ('.pdf','login','privacy','terms','contact','cookie','search','account','/tag/'))):
                    continue
                clean = urlunsplit((url.scheme,url.netloc,url.path,'',''))
                if clean in known or len(url.path.strip('/')) < 8:
                    continue
                candidate = {**parent, 'id': parent['id']+'-'+str(len(known)), 'url': clean,
                             'discovered_from': parent['url']}
                known.add(clean)
                try:
                    retrieve(candidate, cache)
                    sources.append(candidate)
                except Exception:
                    pass
                if len(sources) - len(state['sources']) >= limit:
                    break
        except Exception:
            continue
        if len(sources) - len(state['sources']) >= limit:
            break
    state.update(seen=sorted(known), cursor=(state['cursor']+3) % len(catalog), sources=sources[-180:])
    save(state_path, state)
    return sources[-180:]
