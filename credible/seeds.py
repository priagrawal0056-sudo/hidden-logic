"""Authored fallback episodes. Source passages are verified at preparation time.

These are finite reserves, not permission to endlessly recycle nine topics.
New topics come from the source-grounded generator and its discovery catalog.
"""
from .core import digest, now

# id, title, claim, subject, kind, four spoken beats, four on-screen labels, source search anchor
RECIPES = [
('gps', 'Why Your Map Dot Jumps Beside Tall Buildings',
 'Buildings can block and reflect GPS signals, degrading position accuracy.', 'gps-position', 'map',
 ["Your map dot moved.", "Buildings can reflect GPS signals.",
  "Follow the orange route. It hits a wall before reaching your phone, taking a longer path than the direct signal. Buildings can also block signals entirely.",
  "Both can make your position estimate less reliable. That jumping dot doesn't necessarily mean you moved."],
 ['YOU ARE HERE', 'DIRECT SIGNAL', 'REFLECTED ROUTE', 'POSITION UNCERTAINTY'], 'buildings'),
('bluetooth', 'Bluetooth Keeps Changing Channels While You Listen',
 'Adaptive frequency hopping can avoid radio channels experiencing interference.', 'bluetooth-hopping', 'signal',
 ["Your music keeps playing.", "Bluetooth hops channels to work around interference.",
  "Watch the red lane. In adaptive frequency hopping, channels with interference can be left out of the sequence. The connection uses other channels as it continues.",
  "This drawing slows the process down. Your headphones don't need one permanently empty radio channel to keep a connection."],
 ['A WIRELESS CONNECTION', 'CHANNELS CHANGE', 'BUSY CHANNEL AVOIDED', 'ADAPTIVE HOPPING'], 'avoid channels experiencing'),
('dns', 'What Happens Before a Website Starts Loading',
 'DNS resolves domain names to IP addresses used to reach internet services.', 'dns-resolution', 'process',
 ["You typed a website name.", "DNS finds its internet address.",
  "Your device sends that name to a DNS resolver. Its job is to find the address your browser needs, so you don't have to remember a string of numbers for every website.",
  "Once the address comes back, your browser can contact the website. The name you remember is just where that lookup starts."],
 ['TYPE A WEBSITE NAME', 'ASK THE RESOLVER', 'FIND ITS ADDRESS', 'CONTACT THE WEBSITE'], 'address'),
('roundabout', 'Why a Roundabout Bends Your Approach',
 'Modern roundabouts use curved approaches and yield-at-entry control.', 'roundabout-entry', 'roundabout',
 ["Why that bend?", "A roundabout's curved approach slows arriving traffic.",
  "Now watch the entry. The arriving car must yield to traffic already circulating. It waits for a gap before joining, rather than driving straight into the circle.",
  "The curve and the yield point do different jobs: one reduces approach speed; the other gives circulating traffic priority."],
 ['THE APPROACH BENDS', 'CURVE BEFORE ENTRY', 'YIELD TO THE CIRCLE', 'JOIN THROUGH A GAP'], 'curved approaches'),
('baggage', 'The Small Tag That Identifies Your Checked Bag',
 'Airlines attach baggage destination tags and provide barcode bag-identification labels.', 'baggage-identification', 'barcode',
 ["Which suitcase is yours?", "The airline's tags identify each bag.",
  "It attaches a destination tag to the luggage and gives you a bag identification label with a barcode. The luggage and the label can be identified without relying on their appearance.",
  "Keep that little label until you have your bag back. Similar suitcases can have different identities."],
 ['SIMILAR SUITCASES', 'DESTINATION TAG', 'DISTINCT BAG ID', 'KEEP YOUR LABEL'], 'barcode'),
('screening', 'Why a Checked Bag Can Contain an Inspection Note',
 'TSA screens checked baggage and places a notice inside when physically inspecting a bag.', 'checked-bag-screening', 'process',
 ["A note in your suitcase?", "TSA leaves one after opening a bag.",
  "In the United States, checked baggage goes through screening. Technology can screen bags without opening them, but some need a physical inspection. That's when TSA places the notice inside.",
  "So the paper records a check you didn't see. It doesn't mean every screened bag was opened."],
 ['A NOTE INSIDE', 'CHECKED BAG SCREENING', 'PHYSICAL INSPECTION', 'NOTICE LEFT INSIDE'], 'notice of baggage inspection'),
('unit', 'The Smaller Price on the Shelf Can Tell You More',
 'Unit prices compare the cost of equivalent weights or volumes.', 'unit-pricing', 'comparison',
 ["Which pack is better value?", "Compare prices for the same weight.",
  "Here, a hundred grams costs two dollars. Two hundred grams costs three. That's a dollar fifty per hundred grams for the larger pack, even though its checkout price is higher.",
  "These are example prices. On the shelf, check the unit labels match before comparing the numbers."],
 ['COMPARE TWO PACKS', 'PRICE PER SAME UNIT', 'SMALLER IS NOT LESS', 'CHECK MATCHING UNITS'], 'same weight or volume'),
('barcode', 'A Barcode Does Not Usually Contain the Shelf Price',
 'Ordinary product barcodes identify products whose descriptions and prices are retrieved from a database.', 'product-barcode-lookup', 'barcode',
 ["Same barcode, new price.", "The code identifies an item.",
  "Scan this one and the store's system looks up the item in its database. Change the price there, and the same barcode can bring back the updated price.",
  "The stripes didn't need reprinting. Some special barcodes carry more information, but this is the ordinary product lookup."],
 ['SAME PRODUCT CODE', 'SCAN THE IDENTIFIER', 'LOOK UP THE PRICE', 'DATABASE CAN CHANGE'], 'database'),
('payment', 'Your Contactless Tap Creates a Fresh Security Code',
 'EMV contactless transactions generate a one-time-use security code.', 'emv-contactless-code', 'payment',
 ["Two identical taps.", "EMV payments generate a fresh security code.",
  "Watch the card meet the reader twice. Each contactless transaction gets a one-time code. Code A and code B here are just labels showing that change.",
  "The changing code helps protect against fraud. It's one layer of security; other payment scams are still possible."],
 ['SAME TAPPING MOTION', 'TRANSACTION ONE', 'TRANSACTION TWO', 'A ONE-TIME CODE'], 'one-time')
]


def build_recipe(recipe, source, document):
    from .authored_evidence import PASSAGES
    from .evidence import normalize
    key, title, claim, subject, kind, beats, labels, anchor = recipe
    passages = PASSAGES[key]
    if any(normalize(p).casefold() not in normalize(document['text']).casefold() for p in passages):
        raise ValueError(f'Source changed: reviewed supporting passage missing for {key}')
    from .authored_boards import board
    return {'id': digest([key, beats])[:16], 'title': title, 'claim': claim,
            'claim_id': key + '-mechanism-v1', 'subject': subject,
            'pillar': source['pillar'], 'format': 'comparison' if kind == 'comparison' else 'process',
            'scene_kind': 'storyboard', 'beats': beats, 'labels': labels,
            'production_version': 3, 'storyboard': board(key),
            'source_label': source['publisher'],
            'evidence': [{'claim': claim, 'source_url': source['url'], 'passage': passage,
                          'scope': 'Only the described system; illustrations are not measurements.',
                          'retrieved_at': document['retrieved_at']} for passage in passages],
            'evidence_status': 'source_checked', 'editorial_review': {'supported': True,
                'title_matches': True, 'method': 'authored primary-source review; no generated claims'},
            'authored': True, 'reserved_at': now().isoformat()}
